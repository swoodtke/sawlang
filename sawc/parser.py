"""
Saw Language Parser
Recursive descent parser that builds an AST from tokens.
"""

from typing import List, Optional
from lexer import Token, TokenType
from ast_nodes import (
    Program, Function, Parameter, Block, Statement, Expression,
    LetStatement, AssignStatement, ReturnStatement, ExpressionStatement,
    WhileExpr, BreakStatement, ContinueStatement, ForLoop,
    IntLiteral, FloatLiteral, BoolLiteral, StringLiteral, StringInterpolation, Identifier,
    BinaryOp, UnaryOp, MoveExpr, CastExpr, FunctionCall, IfExpr, IfLetExpr,
    TupleLiteral, TupleIndex, ArrayLiteral, ArrayIndex,
    MemberAccess, StructInit,
    NoneLiteral, ForceUnwrap, NilCoalesce, OptionalChain,
    GuardLetStatement, RangeExpr,
    Struct, StructField,
    Enum, EnumVariant, MatchExpr, MatchArm,
    Extension, Method, MethodCall, SelfExpr,
    Interface, InterfaceMethod, AssociatedType, TypeAssignment, TypeDefinition,
    ExternFunction, ExternBlock,
    SawType, TypeKind, Argument, TypeParameter,
    ClosureExpr, ClosureParam,
    ImportDecl, ModuleDecl
)


class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0
        # Flag to control trailing closure parsing (disabled in if/while/guard conditions)
        self.allow_trailing_closure = True

    def error(self, msg: str):
        token = self.current()
        raise SyntaxError(f"Parse error at {token.line}:{token.column}: {msg}")

    def current(self) -> Token:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return self.tokens[-1]  # EOF

    def peek(self, offset: int = 0) -> Token:
        pos = self.pos + offset
        if pos < len(self.tokens):
            return self.tokens[pos]
        return self.tokens[-1]

    def advance(self) -> Token:
        token = self.current()
        self.pos += 1
        return token

    def match(self, *types: TokenType) -> bool:
        return self.current().type in types

    def expect(self, token_type: TokenType, msg: str = None) -> Token:
        if self.current().type != token_type:
            if msg:
                self.error(msg)
            else:
                self.error(f"Expected {token_type.name}, got {self.current().type.name}")
        return self.advance()

    def skip_newlines(self):
        while self.match(TokenType.NEWLINE):
            self.advance()

    def parse_type_params(self) -> List[TypeParameter]:
        """Parse optional type parameters: <T, U, ...>"""
        if not self.match(TokenType.LT):
            return []

        self.advance()  # consume '<'
        params = []

        # Parse first type parameter
        params.append(self._parse_single_type_param())

        # Parse additional type parameters
        while self.match(TokenType.COMMA):
            self.advance()
            params.append(self._parse_single_type_param())

        self.expect(TokenType.GT, "Expected '>' after type parameters")
        return params

    def _parse_single_type_param(self) -> TypeParameter:
        """Parse a single type parameter: T or T: Bound + OtherBound"""
        start = self.current()
        name_token = self.expect(TokenType.IDENT, "Expected type parameter name")

        # Parse optional bounds: T: Interface1 + Interface2
        bounds = []
        if self.match(TokenType.COLON):
            self.advance()
            # Parse first bound
            bound_token = self.expect(TokenType.IDENT, "Expected interface name after ':'")
            bounds.append(bound_token.value)
            # Parse additional bounds
            while self.match(TokenType.PLUS):
                self.advance()
                bound_token = self.expect(TokenType.IDENT, "Expected interface name after '+'")
                bounds.append(bound_token.value)

        return TypeParameter(
            name=name_token.value,
            bounds=bounds,
            line=start.line,
            column=start.column
        )

    def parse(self) -> Program:
        structs = []
        functions = []
        extensions = []
        enums = []
        interfaces = []
        type_definitions = []
        extern_blocks = []
        imports = []
        module_decls = []
        self.skip_newlines()

        while not self.match(TokenType.EOF):
            if self.match(TokenType.IMPORT):
                imports.append(self.parse_import())
            elif self.match(TokenType.PUBLIC):
                # Could be public module or public struct/func etc. (Phase 3)
                if self.peek(1).type == TokenType.MODULE:
                    module_decls.append(self.parse_module_decl())
                else:
                    # TODO: Handle public declarations in Phase 3
                    self.error("public declarations not yet supported at top level")
            elif self.match(TokenType.MODULE):
                module_decls.append(self.parse_module_decl())
            elif self.match(TokenType.STRUCT):
                structs.append(self.parse_struct())
            elif self.match(TokenType.ENUM):
                enums.append(self.parse_enum())
            elif self.match(TokenType.INTERFACE):
                interfaces.append(self.parse_interface())
            elif self.match(TokenType.EXTENSION):
                extensions.append(self.parse_extension())
            elif self.match(TokenType.FUNC):
                functions.append(self.parse_function())
            elif self.match(TokenType.TYPE):
                type_definitions.append(self.parse_type_definition())
            elif self.match(TokenType.EXTERN):
                extern_blocks.append(self.parse_extern_block())
            else:
                self.error(f"Expected import, module, struct, enum, interface, extension, type, extern, or function declaration, got {self.current().type.name}")
            self.skip_newlines()

        return Program(structs=structs, functions=functions, extensions=extensions,
                       enums=enums, interfaces=interfaces, type_definitions=type_definitions,
                       extern_blocks=extern_blocks, imports=imports, module_decls=module_decls)

    def parse_import(self) -> ImportDecl:
        """Parse import declaration: import path.to.module or import path.{A, B}"""
        start = self.current()
        self.expect(TokenType.IMPORT)

        # Parse the module path
        path = []

        # First component: regular identifier or 'package'/'parent' for relative imports
        # Note: 'package' and 'parent' are NOT keywords to avoid conflicts with user code
        first = self.expect(TokenType.IDENT, "Expected module name after 'import'")
        path.append(first.value)

        # Parse remaining path segments
        while self.match(TokenType.DOT):
            self.advance()

            # Check for glob import: import foo.*
            if self.match(TokenType.STAR):
                self.advance()
                return ImportDecl(
                    path=path,
                    symbols=None,
                    alias=None,
                    is_glob=True,
                    line=start.line,
                    column=start.column
                )

            # Check for symbol set: import foo.{A, B}
            if self.match(TokenType.LBRACE):
                self.advance()
                symbols = []
                if not self.match(TokenType.RBRACE):
                    sym = self.expect(TokenType.IDENT, "Expected symbol name in import")
                    symbols.append(sym.value)
                    while self.match(TokenType.COMMA):
                        self.advance()
                        if self.match(TokenType.RBRACE):
                            break
                        sym = self.expect(TokenType.IDENT, "Expected symbol name in import")
                        symbols.append(sym.value)
                self.expect(TokenType.RBRACE)
                return ImportDecl(
                    path=path,
                    symbols=symbols,
                    alias=None,
                    is_glob=False,
                    line=start.line,
                    column=start.column
                )

            # Regular path component
            component = self.expect(TokenType.IDENT, "Expected module name after '.'")
            path.append(component.value)

        # Check for alias: import foo.bar as baz
        alias = None
        if self.match(TokenType.AS):
            self.advance()
            alias_token = self.expect(TokenType.IDENT, "Expected alias name after 'as'")
            alias = alias_token.value

        return ImportDecl(
            path=path,
            symbols=None,
            alias=alias,
            is_glob=False,
            line=start.line,
            column=start.column
        )

    def parse_module_decl(self) -> ModuleDecl:
        """Parse module declaration: module name or public module name"""
        start = self.current()

        # Check for 'public' modifier
        is_public = False
        if self.match(TokenType.PUBLIC):
            is_public = True
            self.advance()

        self.expect(TokenType.MODULE)
        name_token = self.expect(TokenType.IDENT, "Expected module name")

        # Check for inline module: module name { ... }
        is_inline = False
        body = None
        self.skip_newlines()
        if self.match(TokenType.LBRACE):
            is_inline = True
            self.advance()
            self.skip_newlines()
            # Parse inline module body as a Program
            # For now, we'll parse the contents manually
            structs = []
            functions = []
            extensions = []
            enums = []
            interfaces = []
            type_definitions = []
            extern_blocks = []
            imports = []
            module_decls = []

            while not self.match(TokenType.RBRACE, TokenType.EOF):
                if self.match(TokenType.IMPORT):
                    imports.append(self.parse_import())
                elif self.match(TokenType.PUBLIC):
                    # Could be public module or public struct/func etc.
                    if self.peek(1).type == TokenType.MODULE:
                        module_decls.append(self.parse_module_decl())
                    else:
                        # TODO: Handle public declarations in Phase 3
                        self.error("public declarations not yet supported in inline modules")
                elif self.match(TokenType.MODULE):
                    module_decls.append(self.parse_module_decl())
                elif self.match(TokenType.STRUCT):
                    structs.append(self.parse_struct())
                elif self.match(TokenType.ENUM):
                    enums.append(self.parse_enum())
                elif self.match(TokenType.INTERFACE):
                    interfaces.append(self.parse_interface())
                elif self.match(TokenType.EXTENSION):
                    extensions.append(self.parse_extension())
                elif self.match(TokenType.FUNC):
                    functions.append(self.parse_function())
                elif self.match(TokenType.TYPE):
                    type_definitions.append(self.parse_type_definition())
                elif self.match(TokenType.EXTERN):
                    extern_blocks.append(self.parse_extern_block())
                else:
                    self.error(f"Unexpected token in module: {self.current().type.name}")
                self.skip_newlines()

            self.expect(TokenType.RBRACE)

            body = Program(
                structs=structs,
                functions=functions,
                extensions=extensions,
                enums=enums,
                interfaces=interfaces,
                type_definitions=type_definitions,
                extern_blocks=extern_blocks,
                imports=imports,
                module_decls=module_decls
            )

        return ModuleDecl(
            name=name_token.value,
            is_public=is_public,
            is_inline=is_inline,
            body=body,
            line=start.line,
            column=start.column
        )

    def parse_type(self) -> SawType:
        # Parse base type
        base_type = self._parse_base_type()

        # Check for optional suffix (?)
        if self.match(TokenType.QUESTION):
            self.advance()
            return SawType(TypeKind.OPTIONAL, inner_type=base_type)

        return base_type

    def _parse_base_type(self) -> SawType:
        """Parse a non-optional base type."""
        token = self.current()
        if token.type == TokenType.INT_TYPE:
            self.advance()
            return SawType(TypeKind.INT)
        elif token.type == TokenType.FLOAT_TYPE:
            self.advance()
            return SawType(TypeKind.FLOAT)
        elif token.type == TokenType.BOOL_TYPE:
            self.advance()
            return SawType(TypeKind.BOOL)
        elif token.type == TokenType.STRING_TYPE:
            self.advance()
            return SawType(TypeKind.STRING)
        # Fixed-width integers
        elif token.type == TokenType.INT8_TYPE:
            self.advance()
            return SawType(TypeKind.INT8)
        elif token.type == TokenType.INT16_TYPE:
            self.advance()
            return SawType(TypeKind.INT16)
        elif token.type == TokenType.INT32_TYPE:
            self.advance()
            return SawType(TypeKind.INT32)
        elif token.type == TokenType.INT64_TYPE:
            self.advance()
            return SawType(TypeKind.INT64)
        elif token.type == TokenType.UINT8_TYPE:
            self.advance()
            return SawType(TypeKind.UINT8)
        elif token.type == TokenType.UINT16_TYPE:
            self.advance()
            return SawType(TypeKind.UINT16)
        elif token.type == TokenType.UINT32_TYPE:
            self.advance()
            return SawType(TypeKind.UINT32)
        elif token.type == TokenType.UINT64_TYPE:
            self.advance()
            return SawType(TypeKind.UINT64)
        elif token.type == TokenType.LBRACKET:
            # Array type: [Type; Size]
            self.advance()  # consume '['
            element_type = self.parse_type()
            self.expect(TokenType.SEMICOLON, "Expected ';' in array type")
            size_token = self.expect(TokenType.INT, "Expected array size")
            size = int(size_token.value)
            self.expect(TokenType.RBRACKET, "Expected ']' after array type")
            return SawType(TypeKind.ARRAY, array_element_type=element_type, array_size=size)
        elif token.type == TokenType.LPAREN:
            # Could be tuple type: (Type, Type, ...) or function type: (Type, Type) -> ReturnType
            self.advance()
            element_types = []
            if not self.match(TokenType.RPAREN):
                element_types.append(self.parse_type())
                while self.match(TokenType.COMMA):
                    self.advance()
                    element_types.append(self.parse_type())
            self.expect(TokenType.RPAREN)

            # Check for arrow to distinguish function type from tuple
            if self.match(TokenType.ARROW):
                self.advance()
                return_type = self.parse_type()
                return SawType(TypeKind.FUNCTION, param_types=element_types, func_return_type=return_type)
            else:
                return SawType(TypeKind.TUPLE, element_types=element_types)
        elif token.type == TokenType.IDENT:
            # Could be a struct, enum, type parameter, Self, or pointer type
            self.advance()
            name = token.value

            # Special case for Self type (used in interface method return types)
            if name == "Self":
                return SawType(TypeKind.SELF)

            # Special case for pointer types
            if name == "UnsafePointer":
                type_args = self._parse_type_args()
                if len(type_args) != 1:
                    self.error("UnsafePointer requires exactly one type argument")
                return SawType(TypeKind.POINTER, inner_type=type_args[0], pointer_mutable=True)
            if name == "UnsafeConstPointer":
                type_args = self._parse_type_args()
                if len(type_args) != 1:
                    self.error("UnsafeConstPointer requires exactly one type argument")
                return SawType(TypeKind.POINTER, inner_type=type_args[0], pointer_mutable=False)

            # Check for type arguments: Box<Int>, Pair<A, B>
            type_args = None
            if self.match(TokenType.LT):
                type_args = self._parse_type_args()

            # For now, parse as STRUCT - type checker will determine if it's
            # actually a type parameter or enum
            return SawType(TypeKind.STRUCT, struct_name=name, type_args=type_args)
        else:
            self.error(f"Expected type, got {token.type.name}")

    def _parse_type_args(self) -> List[SawType]:
        """Parse type arguments: <Int, String, ...>"""
        self.expect(TokenType.LT)
        type_args = []

        # Parse first type argument
        type_args.append(self.parse_type())

        # Parse additional type arguments
        while self.match(TokenType.COMMA):
            self.advance()
            type_args.append(self.parse_type())

        self.expect(TokenType.GT, "Expected '>' after type arguments")
        return type_args

    def parse_function(self) -> Function:
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
            line=start.line,
            column=start.column
        )

    def parse_struct(self) -> Struct:
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
            line=start.line,
            column=start.column
        )

    def parse_enum(self) -> Enum:
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
            line=start.line,
            column=start.column
        )

    def parse_interface(self) -> Interface:
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
            line=start.line,
            column=start.column
        )

    def parse_associated_type(self) -> AssociatedType:
        """Parse associated type declaration: type Item"""
        start = self.current()
        self.expect(TokenType.TYPE)

        name_token = self.expect(TokenType.IDENT, "Expected associated type name")

        # TODO: Parse optional bounds: type Item: SomeBound

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

    def parse_extension(self) -> Extension:
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

    def parse_type_definition(self) -> TypeDefinition:
        """Parse top-level type definition: type MyInt = Int"""
        start = self.current()
        self.expect(TokenType.TYPE)

        name_token = self.expect(TokenType.IDENT, "Expected type name")
        self.expect(TokenType.ASSIGN, "Expected '=' after type name")
        defined_type = self.parse_type()

        return TypeDefinition(
            name=name_token.value,
            defined_type=defined_type,
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

    def parse_block(self) -> Block:
        start = self.current()
        self.expect(TokenType.LBRACE)
        self.skip_newlines()

        statements = []
        final_expr = None

        while not self.match(TokenType.RBRACE, TokenType.EOF):
            stmt = self.parse_statement()
            statements.append(stmt)
            self.skip_newlines()

        self.expect(TokenType.RBRACE)

        # Check if last statement is an expression (implicit return)
        if statements and isinstance(statements[-1], ExpressionStatement):
            last = statements.pop()
            final_expr = last.expression

        return Block(
            statements=statements,
            final_expr=final_expr,
            line=start.line,
            column=start.column
        )

    def parse_statement(self) -> Statement:
        if self.match(TokenType.LET):
            return self.parse_let_statement(mutable=False)
        elif self.match(TokenType.VAR):
            return self.parse_let_statement(mutable=True)
        elif self.match(TokenType.GUARD):
            return self.parse_guard_statement()
        elif self.match(TokenType.RETURN):
            return self.parse_return_statement()
        elif self.match(TokenType.WHILE):
            return self.parse_while_statement()
        elif self.match(TokenType.FOR):
            return self.parse_for_statement()
        elif self.match(TokenType.BREAK):
            return self.parse_break_statement()
        elif self.match(TokenType.CONTINUE):
            return self.parse_continue_statement()
        else:
            # Try to parse assignment or expression statement
            # We need to parse the target expression first to handle both
            # simple assignments (x = value) and field assignments (obj.field = value)
            return self.parse_assignment_or_expression_statement()

    def parse_guard_statement(self) -> GuardLetStatement:
        start = self.advance()  # consume 'guard'

        # Expect 'let' or 'var'
        if not (self.match(TokenType.LET) or self.match(TokenType.VAR)):
            self.error("Expected 'let' or 'var' after 'guard'")

        mutable = self.current().type == TokenType.VAR
        self.advance()  # consume 'let' or 'var'

        name_token = self.expect(TokenType.IDENT, "Expected variable name after 'guard let/var'")
        self.expect(TokenType.ASSIGN, "Expected '=' in guard binding")
        # Disable trailing closures - guard is followed by else { }
        saved_trailing = self.allow_trailing_closure
        self.allow_trailing_closure = False
        optional_expr = self.parse_expression()
        self.allow_trailing_closure = saved_trailing

        self.skip_newlines()
        self.expect(TokenType.ELSE, "Expected 'else' in guard statement")
        self.skip_newlines()
        else_branch = self.parse_block()

        return GuardLetStatement(
            name=name_token.value,
            optional_expr=optional_expr,
            mutable=mutable,
            else_branch=else_branch,
            line=start.line,
            column=start.column
        )

    def parse_let_statement(self, mutable: bool) -> LetStatement:
        start = self.advance()  # consume let/var
        name_token = self.expect(TokenType.IDENT, "Expected variable name")

        # Optional type annotation
        type_annotation = None
        if self.match(TokenType.COLON):
            self.advance()
            type_annotation = self.parse_type()

        self.expect(TokenType.ASSIGN, "Expected '=' in variable declaration")
        value = self.parse_expression()

        return LetStatement(
            name=name_token.value,
            type_annotation=type_annotation,
            value=value,
            mutable=mutable,
            line=start.line,
            column=start.column
        )

    def parse_assignment_or_expression_statement(self) -> Statement:
        """Parse either an assignment (x = value, obj.field = value) or expression statement."""
        start_pos = self.pos
        target_expr = self.parse_expression()

        # Check if this is an assignment
        if self.match(TokenType.ASSIGN):
            self.advance()  # consume '='
            value_expr = self.parse_expression()

            # Validate that target is assignable (Identifier, MemberAccess, or ArrayIndex)
            if not isinstance(target_expr, (Identifier, MemberAccess, ArrayIndex)):
                self.error("Invalid assignment target")

            return AssignStatement(
                target=target_expr,
                value=value_expr,
                line=target_expr.line,
                column=target_expr.column
            )
        else:
            # It's just an expression statement
            return ExpressionStatement(
                expression=target_expr,
                line=target_expr.line,
                column=target_expr.column
            )

    def parse_return_statement(self) -> ReturnStatement:
        start = self.advance()  # consume return

        value = None
        if not self.match(TokenType.NEWLINE, TokenType.RBRACE, TokenType.EOF):
            value = self.parse_expression()

        return ReturnStatement(
            value=value,
            line=start.line,
            column=start.column
        )

    def parse_while_statement(self) -> WhileExpr:
        start = self.advance()  # consume 'while'

        # Condition is optional - if we see '{', it's an infinite loop
        condition = None
        if not self.match(TokenType.LBRACE):
            # Disable trailing closures - the { is part of the while body
            saved_trailing = self.allow_trailing_closure
            self.allow_trailing_closure = False
            condition = self.parse_expression()
            self.allow_trailing_closure = saved_trailing

        self.skip_newlines()
        body = self.parse_block()

        return WhileExpr(
            condition=condition,
            body=body,
            line=start.line,
            column=start.column
        )

    def parse_for_statement(self) -> ForLoop:
        """Parse for loop: for variable in iterable { body }"""
        start = self.advance()  # consume 'for'

        # Parse loop variable
        var_token = self.expect(TokenType.IDENT, "Expected variable name after 'for'")

        # Expect 'in' keyword
        self.expect(TokenType.IN, "Expected 'in' after for loop variable")

        # Parse iterable expression (usually a range like 0..10)
        # Disable trailing closures - the { is part of the for body
        saved_trailing = self.allow_trailing_closure
        self.allow_trailing_closure = False
        iterable = self.parse_expression()
        self.allow_trailing_closure = saved_trailing

        self.skip_newlines()
        body = self.parse_block()

        return ForLoop(
            variable=var_token.value,
            iterable=iterable,
            body=body,
            line=start.line,
            column=start.column
        )

    def parse_break_statement(self) -> BreakStatement:
        start = self.advance()  # consume 'break'

        # Check if there's a value to break with
        value = None
        if not self.match(TokenType.NEWLINE, TokenType.RBRACE, TokenType.EOF):
            value = self.parse_expression()

        return BreakStatement(
            value=value,
            line=start.line,
            column=start.column
        )

    def parse_continue_statement(self) -> ContinueStatement:
        start = self.advance()  # consume 'continue'

        return ContinueStatement(
            line=start.line,
            column=start.column
        )

    def parse_expression(self) -> Expression:
        return self.parse_nil_coalesce()

    def parse_nil_coalesce(self) -> Expression:
        """Parse nil coalescing: expr ?? default"""
        left = self.parse_or()

        while self.match(TokenType.DOUBLE_QUESTION):
            op_token = self.advance()
            right = self.parse_or()
            left = NilCoalesce(
                expr=left,
                default=right,
                line=op_token.line,
                column=op_token.column
            )

        return left

    def parse_or(self) -> Expression:
        """Parse logical OR: expr || expr"""
        left = self.parse_and()

        while self.match(TokenType.OR):
            op_token = self.advance()
            right = self.parse_and()
            left = BinaryOp(
                op='||',
                left=left,
                right=right,
                line=op_token.line,
                column=op_token.column
            )

        return left

    def parse_and(self) -> Expression:
        """Parse logical AND: expr && expr"""
        left = self.parse_comparison()

        while self.match(TokenType.AND):
            op_token = self.advance()
            right = self.parse_comparison()
            left = BinaryOp(
                op='&&',
                left=left,
                right=right,
                line=op_token.line,
                column=op_token.column
            )

        return left

    def parse_comparison(self) -> Expression:
        left = self.parse_range()

        while self.match(TokenType.EQ, TokenType.NEQ, TokenType.LT,
                         TokenType.GT, TokenType.LTE, TokenType.GTE):
            op_token = self.advance()
            right = self.parse_range()
            left = BinaryOp(
                op=op_token.value,
                left=left,
                right=right,
                line=op_token.line,
                column=op_token.column
            )

        return left

    def parse_range(self) -> Expression:
        """Parse range expressions: start..end"""
        left = self.parse_additive()

        if self.match(TokenType.DOTDOT):
            op_token = self.advance()
            right = self.parse_additive()
            return RangeExpr(
                start=left,
                end=right,
                line=op_token.line,
                column=op_token.column
            )

        return left

    def parse_additive(self) -> Expression:
        left = self.parse_multiplicative()

        while self.match(TokenType.PLUS, TokenType.MINUS):
            op_token = self.advance()
            right = self.parse_multiplicative()
            left = BinaryOp(
                op=op_token.value,
                left=left,
                right=right,
                line=op_token.line,
                column=op_token.column
            )

        return left

    def parse_multiplicative(self) -> Expression:
        left = self.parse_unary()

        while self.match(TokenType.STAR, TokenType.SLASH, TokenType.PERCENT):
            op_token = self.advance()
            right = self.parse_unary()
            left = BinaryOp(
                op=op_token.value,
                left=left,
                right=right,
                line=op_token.line,
                column=op_token.column
            )

        return left

    def parse_unary(self) -> Expression:
        if self.match(TokenType.MINUS):
            op_token = self.advance()
            operand = self.parse_unary()
            return UnaryOp(
                op='-',
                operand=operand,
                line=op_token.line,
                column=op_token.column
            )

        if self.match(TokenType.NOT):
            op_token = self.advance()
            operand = self.parse_unary()
            return UnaryOp(
                op='not',
                operand=operand,
                line=op_token.line,
                column=op_token.column
            )

        if self.match(TokenType.MOVE):
            move_token = self.advance()
            # move must be followed by an identifier
            if not self.match(TokenType.IDENT):
                raise SyntaxError(f"Expected identifier after 'move' at line {move_token.line}")
            var_token = self.advance()
            return MoveExpr(
                variable=var_token.value,
                line=move_token.line,
                column=move_token.column
            )

        return self.parse_cast()

    def parse_cast(self) -> Expression:
        """Parse type cast: expr as Type"""
        expr = self.parse_postfix()

        while self.match(TokenType.AS):
            as_token = self.advance()
            target_type = self.parse_type()
            expr = CastExpr(
                expr=expr,
                target_type=target_type,
                line=as_token.line,
                column=as_token.column
            )

        return expr

    def parse_postfix(self) -> Expression:
        expr = self.parse_primary()

        # Handle postfix operations: .0, .1, .field, !, ?.
        while True:
            if self.match(TokenType.DOT):
                dot_token = self.advance()
                member_token = self.current()

                if member_token.type == TokenType.INT:
                    # Tuple indexing: expr.0, expr.1, etc.
                    self.advance()
                    index = int(member_token.value)
                    expr = TupleIndex(
                        tuple_expr=expr,
                        index=index,
                        line=dot_token.line,
                        column=dot_token.column
                    )
                elif member_token.type == TokenType.IDENT:
                    # Could be member access or method/enum call
                    member_name = member_token.value
                    self.advance()

                    # Check if followed by '(' - if so, it's a call (method or enum)
                    if self.match(TokenType.LPAREN):
                        # Parse as MethodCall - type checker will determine if it's
                        # actually an enum initialization based on the object type
                        self.advance()  # consume '('
                        arguments = self.parse_arguments()

                        # Check for trailing closure: obj.method(args) { ... }
                        if self.allow_trailing_closure and self.match(TokenType.LBRACE):
                            trailing_closure = self._parse_closure_expression()
                            arguments.append(Argument(value=trailing_closure, name=None))

                        expr = MethodCall(
                            object=expr,
                            method_name=member_name,
                            arguments=arguments,
                            line=dot_token.line,
                            column=dot_token.column
                        )
                    elif self.allow_trailing_closure and self.match(TokenType.LBRACE):
                        # Method call with only trailing closure: obj.method { ... }
                        trailing_closure = self._parse_closure_expression()
                        arguments = [Argument(value=trailing_closure, name=None)]
                        expr = MethodCall(
                            object=expr,
                            method_name=member_name,
                            arguments=arguments,
                            line=dot_token.line,
                            column=dot_token.column
                        )
                    else:
                        # It's just member access (could be simple enum variant or struct field)
                        # For simple enum variants like Status.Success, we create MemberAccess
                        # The type checker will convert this to EnumInit if needed
                        expr = MemberAccess(
                            object=expr,
                            member=member_name,
                            line=dot_token.line,
                            column=dot_token.column
                        )
                else:
                    self.error(f"Expected field name or tuple index after '.', got {member_token.type.name}")

            elif self.match(TokenType.EXCLAIM):
                # Force unwrap: expr!
                exclaim_token = self.advance()
                expr = ForceUnwrap(
                    expr=expr,
                    line=exclaim_token.line,
                    column=exclaim_token.column
                )

            elif self.match(TokenType.QUESTION_DOT):
                # Optional chaining: expr?.member
                chain_token = self.advance()
                member_token = self.expect(TokenType.IDENT, "Expected member name after '?.'")
                expr = OptionalChain(
                    expr=expr,
                    member=member_token.value,
                    line=chain_token.line,
                    column=chain_token.column
                )

            elif self.match(TokenType.LBRACKET):
                # Array indexing: expr[index]
                bracket_token = self.advance()
                index_expr = self.parse_expression()
                self.expect(TokenType.RBRACKET, "Expected ']' after array index")
                expr = ArrayIndex(
                    array_expr=expr,
                    index=index_expr,
                    line=bracket_token.line,
                    column=bracket_token.column
                )

            else:
                break

        return expr

    def parse_primary(self) -> Expression:
        token = self.current()

        if self.match(TokenType.INT):
            self.advance()
            return IntLiteral(value=int(token.value), line=token.line, column=token.column)

        elif self.match(TokenType.FLOAT):
            self.advance()
            return FloatLiteral(value=float(token.value), line=token.line, column=token.column)

        elif self.match(TokenType.TRUE):
            self.advance()
            return BoolLiteral(value=True, line=token.line, column=token.column)

        elif self.match(TokenType.FALSE):
            self.advance()
            return BoolLiteral(value=False, line=token.line, column=token.column)

        elif self.match(TokenType.NONE):
            self.advance()
            return NoneLiteral(line=token.line, column=token.column)

        elif self.match(TokenType.SELF):
            self.advance()
            return SelfExpr(line=token.line, column=token.column)

        elif self.match(TokenType.STRING):
            self.advance()
            return StringLiteral(value=token.value, line=token.line, column=token.column)

        elif self.match(TokenType.INTERP_STRING):
            self.advance()
            return self._parse_interpolated_string(token.value, token.line, token.column)

        elif self.match(TokenType.IDENT):
            self.advance()
            # Check for generic type/function: name<Type>
            # We need to carefully handle the ambiguity between:
            #   foo<Int>(x)    - generic call
            #   foo<Int>.Bar   - generic enum variant access
            #   foo < bar      - comparison
            type_args = None
            if self.match(TokenType.LT):
                # Try to parse as type arguments using backtracking
                saved_pos = self.pos
                try:
                    type_args = self._parse_type_args()
                    # Keep type_args if followed by '(' (function call) or '.' (member access)
                    if not self.match(TokenType.LPAREN) and not self.match(TokenType.DOT):
                        # Not a function call or member access, restore position
                        self.pos = saved_pos
                        type_args = None
                except SyntaxError:
                    # Failed to parse type args, restore position
                    self.pos = saved_pos
                    type_args = None

            # Check for function call or struct initialization
            if self.match(TokenType.LPAREN):
                # Peek ahead to see if this is struct init (name: value) or function call
                if self.peek(1).type == TokenType.IDENT and self.peek(2).type == TokenType.COLON:
                    return self.parse_struct_init(token, type_args)
                else:
                    return self.parse_function_call(token, type_args)
            return Identifier(name=token.value, type_args=type_args, line=token.line, column=token.column)

        elif self.match(TokenType.LPAREN):
            start = self.current()
            self.advance()

            # Empty tuple: ()
            if self.match(TokenType.RPAREN):
                self.advance()
                return TupleLiteral(elements=[], line=start.line, column=start.column)

            # Parse first expression
            first_expr = self.parse_expression()

            # Check if it's a tuple or parenthesized expression
            if self.match(TokenType.COMMA):
                # It's a tuple
                elements = [first_expr]
                while self.match(TokenType.COMMA):
                    self.advance()
                    # Allow trailing comma
                    if self.match(TokenType.RPAREN):
                        break
                    elements.append(self.parse_expression())
                self.expect(TokenType.RPAREN, "Expected ')' after tuple")
                return TupleLiteral(elements=elements, line=start.line, column=start.column)
            else:
                # It's a parenthesized expression
                self.expect(TokenType.RPAREN, "Expected ')' after expression")
                return first_expr

        elif self.match(TokenType.IF):
            return self.parse_if_expression()

        elif self.match(TokenType.MATCH):
            return self.parse_match_expression()

        elif self.match(TokenType.WHILE):
            return self.parse_while_statement()

        elif self.match(TokenType.FOR):
            return self.parse_for_statement()

        elif self.match(TokenType.LBRACKET):
            # Array literal: [1, 2, 3]
            start = self.current()
            self.advance()  # consume '['

            elements = []
            if not self.match(TokenType.RBRACKET):
                elements.append(self.parse_expression())
                while self.match(TokenType.COMMA):
                    self.advance()
                    # Allow trailing comma
                    if self.match(TokenType.RBRACKET):
                        break
                    elements.append(self.parse_expression())

            self.expect(TokenType.RBRACKET, "Expected ']' after array elements")
            return ArrayLiteral(elements=elements, line=start.line, column=start.column)

        elif self.match(TokenType.LBRACE):
            # Closure expression: { x in x * 2 } or { $0 * 2 }
            return self._parse_closure_expression()

        elif self.match(TokenType.DOLLAR_PARAM):
            # Shorthand parameter reference outside of closure (will be validated by typechecker)
            param_token = self.current()
            self.advance()
            return Identifier(name=param_token.value, line=param_token.line, column=param_token.column)

        else:
            self.error(f"Unexpected token: {token.type.name}")

    def parse_arguments(self) -> List[Argument]:
        """Parse a comma-separated list of arguments (named or positional).

        Each argument can be:
        - Named: name: expression
        - Positional: expression

        Called after '(' has been consumed. Consumes the closing ')'.
        """
        arguments = []

        if not self.match(TokenType.RPAREN):
            arguments.append(self._parse_single_argument())
            while self.match(TokenType.COMMA):
                self.advance()
                # Allow trailing comma
                if self.match(TokenType.RPAREN):
                    break
                arguments.append(self._parse_single_argument())

        self.expect(TokenType.RPAREN)
        return arguments

    def _parse_single_argument(self) -> Argument:
        """Parse a single argument which may be named (name: value) or positional (value)."""
        # Check if this is a named argument: identifier followed by ':'
        if self.match(TokenType.IDENT) and self.peek(1).type == TokenType.COLON:
            name = self.advance().value
            self.advance()  # consume ':'
            value = self.parse_expression()
            return Argument(value=value, name=name)
        else:
            # Positional argument
            value = self.parse_expression()
            return Argument(value=value, name=None)

    def parse_function_call(self, name_token: Token, type_args: List[SawType] = None) -> FunctionCall:
        self.expect(TokenType.LPAREN)
        arguments = self.parse_arguments()

        # Check for trailing closure: func(args) { ... }
        if self.allow_trailing_closure and self.match(TokenType.LBRACE):
            trailing_closure = self._parse_closure_expression()
            arguments.append(Argument(value=trailing_closure, name=None))

        return FunctionCall(
            name=name_token.value,
            arguments=arguments,
            type_args=type_args,
            line=name_token.line,
            column=name_token.column
        )

    def parse_struct_init(self, name_token: Token, type_args: Optional[List[SawType]] = None) -> StructInit:
        """Parse struct initialization: StructName(field1: value1) or Box<Int>(value: 42)"""
        self.expect(TokenType.LPAREN)
        field_inits = []

        if not self.match(TokenType.RPAREN):
            # Parse first field
            field_name = self.expect(TokenType.IDENT, "Expected field name").value
            self.expect(TokenType.COLON, "Expected ':' after field name")
            field_value = self.parse_expression()
            field_inits.append((field_name, field_value))

            # Parse remaining fields
            while self.match(TokenType.COMMA):
                self.advance()
                # Allow trailing comma
                if self.match(TokenType.RPAREN):
                    break
                field_name = self.expect(TokenType.IDENT, "Expected field name").value
                self.expect(TokenType.COLON, "Expected ':' after field name")
                field_value = self.parse_expression()
                field_inits.append((field_name, field_value))

        self.expect(TokenType.RPAREN)

        return StructInit(
            struct_name=name_token.value,
            field_inits=field_inits,
            type_args=type_args,
            line=name_token.line,
            column=name_token.column
        )

    def parse_if_expression(self) -> Expression:
        start = self.advance()  # consume 'if'

        # Check for 'if let' or 'if var' optional binding
        if self.match(TokenType.LET) or self.match(TokenType.VAR):
            mutable = self.current().type == TokenType.VAR
            self.advance()  # consume 'let' or 'var'

            name_token = self.expect(TokenType.IDENT, "Expected variable name after 'if let/var'")
            self.expect(TokenType.ASSIGN, "Expected '=' in optional binding")
            # Disable trailing closures - the { is part of the if block
            saved_trailing = self.allow_trailing_closure
            self.allow_trailing_closure = False
            optional_expr = self.parse_expression()
            self.allow_trailing_closure = saved_trailing

            self.skip_newlines()
            then_branch = self.parse_block()

            else_branch = None
            self.skip_newlines()
            if self.match(TokenType.ELSE):
                self.advance()
                self.skip_newlines()
                # Check for 'else if' - parse as nested if expression
                if self.match(TokenType.IF):
                    nested_if = self.parse_if_expression()
                    # Wrap the nested if in a Block with it as the final expression
                    else_branch = Block(
                        statements=[],
                        final_expr=nested_if,
                        line=nested_if.line,
                        column=nested_if.column
                    )
                else:
                    else_branch = self.parse_block()

            return IfLetExpr(
                name=name_token.value,
                optional_expr=optional_expr,
                mutable=mutable,
                then_branch=then_branch,
                else_branch=else_branch,
                line=start.line,
                column=start.column
            )

        # Regular if expression - disable trailing closures
        saved_trailing = self.allow_trailing_closure
        self.allow_trailing_closure = False
        condition = self.parse_expression()
        self.allow_trailing_closure = saved_trailing
        self.skip_newlines()
        then_branch = self.parse_block()

        else_branch = None
        self.skip_newlines()
        if self.match(TokenType.ELSE):
            self.advance()
            self.skip_newlines()
            # Check for 'else if' - parse as nested if expression
            if self.match(TokenType.IF):
                nested_if = self.parse_if_expression()
                # Wrap the nested if in a Block with it as the final expression
                else_branch = Block(
                    statements=[],
                    final_expr=nested_if,
                    line=nested_if.line,
                    column=nested_if.column
                )
            else:
                else_branch = self.parse_block()

        return IfExpr(
            condition=condition,
            then_branch=then_branch,
            else_branch=else_branch,
            line=start.line,
            column=start.column
        )

    def parse_match_expression(self) -> MatchExpr:
        """Parse match expression: match value { case Variant -> expr, ... }"""
        start = self.advance()  # consume 'match'

        # Parse the expression being matched - disable trailing closures
        saved_trailing = self.allow_trailing_closure
        self.allow_trailing_closure = False
        matched_expr = self.parse_expression()
        self.allow_trailing_closure = saved_trailing

        self.skip_newlines()
        self.expect(TokenType.LBRACE, "Expected '{' after match expression")
        self.skip_newlines()

        # Parse match arms
        arms = []
        while not self.match(TokenType.RBRACE, TokenType.EOF):
            arm_start = self.current()
            self.expect(TokenType.CASE, "Expected 'case' keyword in match arm")

            # Parse variant name
            variant_token = self.expect(TokenType.IDENT, "Expected variant name after 'case'")
            variant_name = variant_token.value

            # Parse optional bindings: case Variant(x, y)
            bindings = []
            if self.match(TokenType.LPAREN):
                self.advance()
                if not self.match(TokenType.RPAREN):
                    # Parse first binding
                    binding_token = self.expect(TokenType.IDENT, "Expected binding name")
                    bindings.append(binding_token.value)

                    # Parse additional bindings
                    while self.match(TokenType.COMMA):
                        self.advance()
                        binding_token = self.expect(TokenType.IDENT, "Expected binding name")
                        bindings.append(binding_token.value)

                self.expect(TokenType.RPAREN)

            # Parse arrow
            self.expect(TokenType.ARROW, "Expected '->' after match pattern")

            # Parse arm body (can be expression or block)
            if self.match(TokenType.LBRACE):
                body = self.parse_block()
            else:
                body = self.parse_expression()

            arms.append(MatchArm(
                variant_name=variant_name,
                bindings=bindings,
                body=body,
                line=arm_start.line,
                column=arm_start.column
            ))

            self.skip_newlines()
            # Allow optional comma after arm
            if self.match(TokenType.COMMA):
                self.advance()
            self.skip_newlines()

        self.expect(TokenType.RBRACE, "Expected '}' at end of match expression")

        return MatchExpr(
            matched_expr=matched_expr,
            arms=arms,
            line=start.line,
            column=start.column
        )

    # === Closure Parsing ===

    def _parse_closure_expression(self) -> ClosureExpr:
        """Parse a closure expression: { x in x * 2 } or { $0 * 2 }"""
        start = self.current()
        self.advance()  # consume '{'
        self.skip_newlines()

        # Check for named params: { x in ... } or { x, y in ... } or { x: Type in ... }
        params = []
        if self._is_closure_with_named_params():
            params = self._parse_closure_params()
            self.expect(TokenType.IN, "Expected 'in' after closure parameters")
            self.skip_newlines()

        # Parse body as block-like content
        body = self._parse_closure_body()
        self.expect(TokenType.RBRACE, "Expected '}' at end of closure")

        # Count $N parameters if no named params
        shorthand_count = 0
        if not params:
            shorthand_count = self._count_shorthand_params(body)

        return ClosureExpr(
            parameters=params,
            body=body,
            shorthand_param_count=shorthand_count,
            line=start.line,
            column=start.column
        )

    def _is_closure_with_named_params(self) -> bool:
        """Look ahead to check for pattern: IDENT (':' Type)? (',' IDENT (':' Type)?)* 'in'"""
        saved_pos = self.pos
        try:
            # Must start with identifier
            if not self.match(TokenType.IDENT):
                return False

            # Scan ahead for 'in' keyword
            # Keep track of nesting for type annotations
            depth = 0
            while True:
                token = self.current()
                if token.type == TokenType.EOF or token.type == TokenType.RBRACE:
                    return False
                if token.type == TokenType.IN and depth == 0:
                    return True
                if token.type == TokenType.LT or token.type == TokenType.LPAREN:
                    depth += 1
                if token.type == TokenType.GT or token.type == TokenType.RPAREN:
                    depth -= 1
                # If we see operators or statements, this isn't a param list
                if depth == 0 and token.type in (
                    TokenType.PLUS, TokenType.MINUS, TokenType.STAR, TokenType.SLASH,
                    TokenType.EQ, TokenType.NEQ, TokenType.LET, TokenType.VAR,
                    TokenType.RETURN, TokenType.IF, TokenType.WHILE,
                    TokenType.ASSIGN, TokenType.SEMICOLON
                ):
                    return False
                self.advance()
        finally:
            self.pos = saved_pos

    def _parse_closure_params(self) -> List[ClosureParam]:
        """Parse closure parameters: x, y: Int, z"""
        params = []

        while True:
            param_token = self.expect(TokenType.IDENT, "Expected parameter name")

            # Check for optional type annotation
            type_ann = None
            if self.match(TokenType.COLON):
                self.advance()
                type_ann = self.parse_type()

            params.append(ClosureParam(
                name=param_token.value,
                type_annotation=type_ann,
                line=param_token.line,
                column=param_token.column
            ))

            if not self.match(TokenType.COMMA):
                break
            self.advance()
            self.skip_newlines()

        return params

    def _parse_closure_body(self) -> Block:
        """Parse closure body as a block (statements + optional final expression)."""
        statements = []
        final_expr = None
        start = self.current()

        while not self.match(TokenType.RBRACE) and not self.match(TokenType.EOF):
            self.skip_newlines()
            if self.match(TokenType.RBRACE):
                break

            # Try to parse a statement
            stmt = self._parse_closure_statement()
            if stmt:
                statements.append(stmt)
            self.skip_newlines()

        # Check if last statement is expression (implicit return)
        if statements and isinstance(statements[-1], ExpressionStatement):
            last = statements.pop()
            final_expr = last.expression

        return Block(
            statements=statements,
            final_expr=final_expr,
            line=start.line,
            column=start.column
        )

    def _parse_closure_statement(self) -> Optional[Statement]:
        """Parse a single statement in a closure body."""
        if self.match(TokenType.LET):
            return self.parse_let_statement()
        elif self.match(TokenType.VAR):
            return self.parse_let_statement()
        elif self.match(TokenType.RETURN):
            start = self.current()
            self.advance()
            value = None
            if not self.match(TokenType.NEWLINE) and not self.match(TokenType.RBRACE):
                value = self.parse_expression()
            return ReturnStatement(value=value, line=start.line, column=start.column)
        else:
            # Expression statement
            expr = self.parse_expression()
            return ExpressionStatement(expression=expr, line=expr.line, column=expr.column)

    def _parse_interpolated_string(self, raw_value: str, line: int, column: int) -> StringInterpolation:
        """Parse a string with {expr} interpolations into parts and expressions.

        The raw_value contains the string with braces preserved, e.g. "Hello {name}!"
        Returns a StringInterpolation node with parts and expressions separated.
        """
        from lexer import Lexer

        parts = []
        expressions = []
        current_part = []
        i = 0

        while i < len(raw_value):
            if raw_value[i] == '{':
                # Save current string part
                parts.append(''.join(current_part))
                current_part = []

                # Extract expression text between { and }
                i += 1  # skip {
                brace_depth = 1
                expr_chars = []
                while i < len(raw_value) and brace_depth > 0:
                    ch = raw_value[i]
                    if ch == '{':
                        brace_depth += 1
                    elif ch == '}':
                        brace_depth -= 1
                    if brace_depth > 0:
                        expr_chars.append(ch)
                    i += 1

                # Parse the expression using a sub-lexer and sub-parser
                expr_str = ''.join(expr_chars)
                expr = self._parse_expression_from_string(expr_str, line, column)
                expressions.append(expr)
            else:
                current_part.append(raw_value[i])
                i += 1

        # Final string part (after last expression or entire string if no expressions)
        parts.append(''.join(current_part))

        return StringInterpolation(parts=parts, expressions=expressions, line=line, column=column)

    def _parse_expression_from_string(self, expr_str: str, line: int, column: int) -> Expression:
        """Parse a string as an expression using a sub-lexer/parser."""
        from lexer import Lexer

        sub_lexer = Lexer(expr_str)
        sub_tokens = sub_lexer.tokenize()

        # Create a sub-parser with these tokens
        sub_parser = Parser(sub_tokens)
        return sub_parser.parse_expression()

    def _count_shorthand_params(self, body: Block) -> int:
        """Count the maximum $N parameter index used in the closure body."""
        max_index = -1

        def visit_expr(expr):
            nonlocal max_index
            if expr is None:
                return

            if isinstance(expr, Identifier):
                if expr.name.startswith('$') and expr.name[1:].isdigit():
                    index = int(expr.name[1:])
                    max_index = max(max_index, index)
            elif isinstance(expr, BinaryOp):
                visit_expr(expr.left)
                visit_expr(expr.right)
            elif isinstance(expr, UnaryOp):
                visit_expr(expr.operand)
            elif isinstance(expr, FunctionCall):
                for arg in expr.arguments:
                    visit_expr(arg.value)
            elif isinstance(expr, MethodCall):
                visit_expr(expr.object)
                for arg in expr.arguments:
                    visit_expr(arg.value)
            elif isinstance(expr, IfExpr):
                visit_expr(expr.condition)
                visit_block(expr.then_branch)
                if expr.else_branch:
                    visit_block(expr.else_branch)
            elif isinstance(expr, TupleLiteral):
                for elem in expr.elements:
                    visit_expr(elem)
            elif isinstance(expr, ArrayLiteral):
                for elem in expr.elements:
                    visit_expr(elem)
            elif isinstance(expr, ArrayIndex):
                visit_expr(expr.array_expr)
                visit_expr(expr.index)
            elif isinstance(expr, MemberAccess):
                visit_expr(expr.object)
            elif isinstance(expr, ForceUnwrap):
                visit_expr(expr.expr)
            elif isinstance(expr, NilCoalesce):
                visit_expr(expr.expr)
                visit_expr(expr.default)
            elif isinstance(expr, OptionalChain):
                visit_expr(expr.expr)
            elif isinstance(expr, ClosureExpr):
                # Don't recurse into nested closures - they have their own params
                pass

        def visit_block(block):
            if block is None:
                return
            for stmt in block.statements:
                if isinstance(stmt, ExpressionStatement):
                    visit_expr(stmt.expression)
                elif isinstance(stmt, LetStatement):
                    visit_expr(stmt.value)
                elif isinstance(stmt, AssignStatement):
                    visit_expr(stmt.value)
                elif isinstance(stmt, ReturnStatement):
                    visit_expr(stmt.value)
            if block.final_expr:
                visit_expr(block.final_expr)

        visit_block(body)
        return max_index + 1 if max_index >= 0 else 0

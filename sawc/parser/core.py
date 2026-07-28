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
    Trait, TraitMethod, AssociatedType, TypeAssignment, TypeDefinition,
    ExternFunction, ExternBlock,
    SawType, TypeKind, Argument, TypeParameter,
    ClosureExpr, ClosureParam,
    ImportDecl, ModuleDecl, ExportDecl, Visibility
)
from .types import TypeParsingMixin
from .declarations import DeclarationsMixin
from .statements import StatementsMixin
from .expressions import ExpressionsMixin


class Parser(ExpressionsMixin, StatementsMixin, DeclarationsMixin, TypeParsingMixin):
    def __init__(self, tokens: List[Token], source_file: str = ""):
        self.tokens = tokens
        self.pos = 0
        # Flag to control trailing closure parsing (disabled in if/while/guard conditions)
        self.allow_trailing_closure = True
        # Track source file for error reporting
        self.source_file = source_file

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

    def match_ident(self, value: str) -> bool:
        """Check if current token is IDENT with the given value (for context-sensitive keywords)."""
        return self.current().type == TokenType.IDENT and self.current().value == value

    def expect_ident(self, value: str, msg: str = None) -> Token:
        """Expect an IDENT token with the given value (for context-sensitive keywords)."""
        if not self.match_ident(value):
            if msg:
                self.error(msg)
            else:
                self.error(f"Expected '{value}', got {self.current().type.name}")
        return self.advance()

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

    def _parse_visibility(self) -> Visibility:
        """Parse optional visibility modifier: public, public(package), public(parent)."""
        if not self.match(TokenType.PUBLIC):
            return Visibility.PRIVATE

        self.advance()  # consume 'public'

        # Check for public(package) or public(parent)
        if self.match(TokenType.LPAREN):
            self.advance()  # consume '('
            if not self.match(TokenType.IDENT):
                self.error("Expected 'package' or 'parent' after 'public('")
            modifier = self.current().value
            self.advance()

            if modifier == "package":
                visibility = Visibility.PACKAGE
            elif modifier == "parent":
                visibility = Visibility.PARENT
            else:
                self.error(f"Unknown visibility modifier: public({modifier}). Expected 'package' or 'parent'")

            self.expect(TokenType.RPAREN, "Expected ')' after visibility modifier")
            return visibility

        return Visibility.PUBLIC

    def _parse_single_type_param(self) -> TypeParameter:
        """Parse a single type parameter: T or T: Bound + OtherBound"""
        start = self.current()
        name_token = self.expect(TokenType.IDENT, "Expected type parameter name")

        # Parse optional bounds: T: Trait1 + Trait2
        bounds = []
        if self.match(TokenType.COLON):
            self.advance()
            # Parse first bound
            bound_token = self.expect(TokenType.IDENT, "Expected trait name after ':'")
            bounds.append(bound_token.value)
            # Parse additional bounds
            while self.match(TokenType.PLUS):
                self.advance()
                bound_token = self.expect(TokenType.IDENT, "Expected trait name after '+'")
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
        traits = []
        type_definitions = []
        extern_blocks = []
        imports = []
        module_decls = []
        exports = []
        self.skip_newlines()

        while not self.match(TokenType.EOF):
            if self.match_ident("import"):
                imports.append(self.parse_import())
            elif self.match_ident("export"):
                exports.append(self.parse_export())
            elif self.match(TokenType.PUBLIC):
                # Could be public module or public declaration
                if self.peek(1).type == TokenType.IDENT and self.peek(1).value == "module":
                    module_decls.append(self.parse_module_decl())
                else:
                    # Parse visibility and then the declaration
                    visibility = self._parse_visibility()
                    if self.match(TokenType.STRUCT):
                        structs.append(self.parse_struct(visibility))
                    elif self.match(TokenType.ENUM):
                        enums.append(self.parse_enum(visibility))
                    elif self.match(TokenType.TRAIT):
                        traits.append(self.parse_trait(visibility))
                    elif self.match(TokenType.EXTENSION):
                        extensions.append(self.parse_extension(visibility))
                    elif self.match(TokenType.FUNC):
                        functions.append(self.parse_function(visibility))
                    elif self.match(TokenType.TYPE):
                        type_definitions.append(self.parse_type_definition(visibility))
                    else:
                        self.error(f"Expected struct, enum, trait, extension, func, or type after visibility modifier")
            elif self.match_ident("module"):
                module_decls.append(self.parse_module_decl())
            elif self.match(TokenType.STRUCT):
                structs.append(self.parse_struct())
            elif self.match(TokenType.ENUM):
                enums.append(self.parse_enum())
            elif self.match(TokenType.TRAIT):
                traits.append(self.parse_trait())
            elif self.match(TokenType.EXTENSION):
                extensions.append(self.parse_extension())
            elif self.match(TokenType.FUNC):
                functions.append(self.parse_function())
            elif self.match(TokenType.TYPE):
                type_definitions.append(self.parse_type_definition())
            elif self.match(TokenType.EXTERN):
                extern_blocks.append(self.parse_extern_block())
            else:
                self.error(f"Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got {self.current().type.name}")
            self.skip_newlines()

        return Program(structs=structs, functions=functions, extensions=extensions,
                       enums=enums, traits=traits, type_definitions=type_definitions,
                       extern_blocks=extern_blocks, imports=imports, module_decls=module_decls,
                       exports=exports)

    def parse_import(self) -> ImportDecl:
        """Parse import declaration: import path.to.module or import path.{A, B}"""
        start = self.current()
        self.expect_ident("import")

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

    def parse_export(self) -> ExportDecl:
        """Parse export declaration for init.saw facades.

        Syntax:
        - export path.to.Symbol
        - export path.to.Symbol as AliasName
        - export path.to.*
        """
        start = self.current()
        self.expect_ident("export")

        # Parse the path
        path = []
        first = self.expect(TokenType.IDENT, "Expected path after 'export'")
        path.append(first.value)

        # Parse remaining path segments
        while self.match(TokenType.DOT):
            self.advance()

            # Check for glob export: export foo.*
            if self.match(TokenType.STAR):
                self.advance()
                return ExportDecl(
                    path=path,
                    alias=None,
                    is_glob=True,
                    line=start.line,
                    column=start.column
                )

            # Regular path component
            component = self.expect(TokenType.IDENT, "Expected name after '.'")
            path.append(component.value)

        # Check for alias: export foo.bar as baz
        alias = None
        if self.match(TokenType.AS):
            self.advance()
            alias_token = self.expect(TokenType.IDENT, "Expected alias name after 'as'")
            alias = alias_token.value

        return ExportDecl(
            path=path,
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

        self.expect_ident("module")
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
            traits = []
            type_definitions = []
            extern_blocks = []
            imports = []
            module_decls = []
            exports = []

            while not self.match(TokenType.RBRACE, TokenType.EOF):
                if self.match_ident("import"):
                    imports.append(self.parse_import())
                elif self.match_ident("export"):
                    exports.append(self.parse_export())
                elif self.match(TokenType.PUBLIC):
                    # Could be public module or public declaration
                    if self.peek(1).type == TokenType.IDENT and self.peek(1).value == "module":
                        module_decls.append(self.parse_module_decl())
                    else:
                        # Parse visibility and then the declaration
                        visibility = self._parse_visibility()
                        if self.match(TokenType.STRUCT):
                            structs.append(self.parse_struct(visibility))
                        elif self.match(TokenType.ENUM):
                            enums.append(self.parse_enum(visibility))
                        elif self.match(TokenType.TRAIT):
                            traits.append(self.parse_trait(visibility))
                        elif self.match(TokenType.EXTENSION):
                            extensions.append(self.parse_extension(visibility))
                        elif self.match(TokenType.FUNC):
                            functions.append(self.parse_function(visibility))
                        elif self.match(TokenType.TYPE):
                            type_definitions.append(self.parse_type_definition(visibility))
                        else:
                            self.error(f"Expected struct, enum, trait, extension, func, or type after visibility modifier")
                elif self.match_ident("module"):
                    module_decls.append(self.parse_module_decl())
                elif self.match(TokenType.STRUCT):
                    structs.append(self.parse_struct())
                elif self.match(TokenType.ENUM):
                    enums.append(self.parse_enum())
                elif self.match(TokenType.TRAIT):
                    traits.append(self.parse_trait())
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
                traits=traits,
                type_definitions=type_definitions,
                extern_blocks=extern_blocks,
                imports=imports,
                module_decls=module_decls,
                exports=exports
            )

        return ModuleDecl(
            name=name_token.value,
            is_public=is_public,
            is_inline=is_inline,
            body=body,
            line=start.line,
            column=start.column
        )

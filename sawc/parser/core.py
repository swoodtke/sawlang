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

        # Parse optional default: `A: Allocator = Global` (design 37). Default
        # type parameters — a TYPE after `=`, never a value. Enables the allocator
        # to be omitted at hosted reference sites (`Vector<Int>`) while the type
        # system still carries the full `Vector<Int, Global>` identity.
        default = None
        if self.match(TokenType.ASSIGN):
            self.advance()  # consume '='
            default = self.parse_type()

        return TypeParameter(
            name=name_token.value,
            bounds=bounds,
            default=default,
            line=start.line,
            column=start.column
        )

    # Maximum syntax errors collected before bailing out of a single file.
    MAX_PARSE_ERRORS = 10

    def _at_toplevel_start(self) -> bool:
        """True if the current token can begin a top-level declaration."""
        t = self.current()
        if t.type in (TokenType.FUNC, TokenType.STRUCT, TokenType.ENUM,
                      TokenType.EXTENSION, TokenType.TRAIT, TokenType.TYPE,
                      TokenType.EXTERN, TokenType.STATIC, TokenType.PUBLIC,
                      TokenType.AT):
            return True
        if t.type == TokenType.IDENT and t.value in ("import", "module", "export"):
            return True
        return False

    def _synchronize(self):
        """Recover from a syntax error by skipping to the next top-level
        declaration boundary (`func`/`struct`/`enum`/`extension`/`trait`/
        `type`/`extern`/`import`/`module`/`export` at brace depth 0).

        Always consumes at least one token so the parse loop makes forward
        progress (otherwise re-dispatching on the same offending token would
        loop forever). Braces are tracked so a top-level keyword nested inside a
        malformed body is not mistaken for a boundary; an unmatched closing
        brace at depth 0 also ends recovery.
        """
        depth = 0
        first = True  # skip the offending token before honoring any boundary
        while not self.match(TokenType.EOF):
            t = self.current()
            if t.type == TokenType.LBRACE:
                depth += 1
                self.advance()
            elif t.type == TokenType.RBRACE:
                if depth > 0:
                    depth -= 1
                    self.advance()
                else:
                    # Stray closing brace at depth 0: consume it and resume.
                    self.advance()
                    return
            elif not first and depth == 0 and self._at_toplevel_start():
                return
            else:
                self.advance()
            first = False

    def _parse_toplevel_decl(self, p: Program):
        """Parse ONE top-level declaration at the current token and append it to
        the matching list of `p` (design 40 item 8 — the dispatch shared by the
        file-level `parse()` loop and inline-module bodies, so it lives in one
        place). Raises SyntaxError on a token that cannot begin a declaration;
        the caller owns loop control, the `EOF`/`RBRACE` terminator, and (in
        `parse()` only) the batched error recovery around each call.
        """
        # Attributes (design 58): zero or more `@name`/`@name("arg")` lines
        # immediately preceding a declaration. v1 legal ONLY on top-level
        # func/static; anything else is a clean "attributes are not supported"
        # error routed through `_parse_attributed_decl`.
        if self.match(TokenType.AT):
            attrs = self.parse_attributes()
            self.skip_newlines()
            return self._parse_attributed_decl(p, attrs)

        if self.match_ident("import"):
            p.imports.append(self.parse_import())
        elif self.match_ident("export"):
            p.exports.append(self.parse_export())
        elif self.match_ident("static_assert") and self.peek(1).type == TokenType.LPAREN:
            p.static_asserts.append(self.parse_static_assert())
        elif self.match(TokenType.PUBLIC):
            # Could be public module or public declaration
            if self.peek(1).type == TokenType.IDENT and self.peek(1).value == "module":
                p.module_decls.append(self.parse_module_decl())
            else:
                # Parse visibility and then the declaration
                visibility = self._parse_visibility()
                if self.match(TokenType.STRUCT):
                    p.structs.append(self.parse_struct(visibility))
                elif self.match(TokenType.ENUM):
                    p.enums.append(self.parse_enum(visibility))
                elif self.match(TokenType.TRAIT):
                    p.traits.append(self.parse_trait(visibility))
                elif self.match(TokenType.EXTENSION):
                    p.extensions.append(self.parse_extension(visibility))
                elif self.match(TokenType.FUNC):
                    p.functions.append(self.parse_function(visibility))
                elif self.match(TokenType.TYPE):
                    p.type_definitions.append(self.parse_type_definition(visibility))
                elif self.match(TokenType.STATIC):
                    p.statics.append(self.parse_static(visibility))
                else:
                    self.error(f"Expected struct, enum, trait, extension, func, type, or static after visibility modifier")
        elif self.match_ident("module"):
            p.module_decls.append(self.parse_module_decl())
        elif self.match(TokenType.STRUCT):
            p.structs.append(self.parse_struct())
        elif self.match(TokenType.ENUM):
            p.enums.append(self.parse_enum())
        elif self.match(TokenType.TRAIT):
            p.traits.append(self.parse_trait())
        elif self.match(TokenType.EXTENSION):
            p.extensions.append(self.parse_extension())
        elif self.match(TokenType.FUNC):
            p.functions.append(self.parse_function())
        elif self.match(TokenType.TYPE):
            p.type_definitions.append(self.parse_type_definition())
        elif self.match(TokenType.EXTERN):
            p.extern_blocks.append(self.parse_extern_block())
        elif self.match(TokenType.STATIC):
            p.statics.append(self.parse_static())
        else:
            self.error(f"Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got {self.current().type.name}")

    def _parse_attributed_decl(self, p: Program, attrs):
        """Parse the declaration following an attribute block and attach `attrs`.

        design 58 v1: attributes are legal ONLY on top-level `func` and `static`
        (optionally `public`-prefixed). Everything else gets a clean
        "attributes are not supported on X" error.
        """
        visibility = Visibility.PRIVATE
        if self.match(TokenType.PUBLIC):
            # `public module` is not an attributable declaration.
            if self.peek(1).type == TokenType.IDENT and self.peek(1).value == "module":
                self.error("attributes are not supported on module declarations")
            visibility = self._parse_visibility()

        if self.match(TokenType.FUNC):
            fn = self.parse_function(visibility)
            fn.attributes = attrs
            p.functions.append(fn)
        elif self.match(TokenType.STATIC):
            st = self.parse_static(visibility)
            st.attributes = attrs
            p.statics.append(st)
        else:
            self.error(f"attributes are not supported on {self._describe_decl_kind()}")

    def _describe_decl_kind(self) -> str:
        """Human phrase for the declaration at the current token (used in the
        'attributes are not supported on X' diagnostic)."""
        t = self.current()
        mapping = {
            TokenType.STRUCT: "struct declarations",
            TokenType.ENUM: "enum declarations",
            TokenType.TRAIT: "trait declarations",
            TokenType.EXTENSION: "extensions",
            TokenType.TYPE: "type declarations",
            TokenType.EXTERN: "extern blocks",
        }
        if t.type in mapping:
            return mapping[t.type]
        if t.type == TokenType.IDENT and t.value in ("import", "module", "export"):
            return f"{t.value} declarations"
        return "this declaration"

    def parse(self) -> Program:
        program = Program(structs=[], functions=[])
        errors = []  # collected syntax error messages (batched recovery)
        self.skip_newlines()

        while not self.match(TokenType.EOF):
            try:
                self._parse_toplevel_decl(program)
            except SyntaxError as e:
                # Batch syntax errors: record this one, then synchronize to the
                # next top-level declaration and keep parsing so a single file
                # can report multiple independent errors in one run.
                errors.append(str(e))
                if len(errors) >= self.MAX_PARSE_ERRORS:
                    break
                self._synchronize()
            self.skip_newlines()

        if errors:
            # Surface all collected errors. A single error reproduces the exact
            # prior message; multiple are joined so every one reaches the report.
            raise SyntaxError("\n".join(errors))

        return program

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

            # Check for symbol set: import foo.{A, B as C} (design 53: per-symbol
            # `as` aliases).
            if self.match(TokenType.LBRACE):
                self.advance()
                symbols = []
                symbol_aliases = {}
                local_names = set()

                def parse_one_symbol():
                    sym = self.expect(TokenType.IDENT, "Expected symbol name in import")
                    symbols.append(sym.value)
                    local = sym.value
                    if self.match(TokenType.AS):
                        self.advance()
                        alias_tok = self.expect(TokenType.IDENT,
                                                "Expected alias name after 'as'")
                        symbol_aliases[sym.value] = alias_tok.value
                        local = alias_tok.value
                    # design 53: two entries of one selective import may not bind
                    # the same local name (an alias colliding with another
                    # imported name), reported with the offending local name.
                    if local in local_names:
                        self.error(f"imported name `{local}` is already bound by "
                                   f"this import")
                    local_names.add(local)

                if not self.match(TokenType.RBRACE):
                    parse_one_symbol()
                    while self.match(TokenType.COMMA):
                        self.advance()
                        if self.match(TokenType.RBRACE):
                            break
                        parse_one_symbol()
                self.expect(TokenType.RBRACE)
                return ImportDecl(
                    path=path,
                    symbols=symbols,
                    alias=None,
                    is_glob=False,
                    line=start.line,
                    column=start.column,
                    symbol_aliases=(symbol_aliases or None)
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

    def parse_static_assert(self):
        """Parse `static_assert(<const-expr>, "message")` (design 53). Legal at
        top level and in statement position. The message must be a plain string
        literal (it is baked into the compile-time diagnostic)."""
        from ast_nodes import StaticAssert
        start = self.current()
        self.advance()  # consume 'static_assert' identifier
        self.expect(TokenType.LPAREN, "Expected '(' after `static_assert`")
        condition = self.parse_expression()
        self.expect(TokenType.COMMA, "Expected ',' after the static_assert condition")
        msg_tok = self.expect(TokenType.STRING,
                              "static_assert message must be a plain string literal")
        self.expect(TokenType.RPAREN, "Expected ')' to close `static_assert`")
        return StaticAssert(
            condition=condition,
            message=msg_tok.value,
            line=start.line,
            column=start.column,
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
            # Parse the inline module body as a Program, reusing the shared
            # top-level dispatch (design 40 item 8). Inline modules do NOT run
            # batched error recovery — a syntax error here propagates to the
            # file-level `parse()` loop, which synchronizes past the whole
            # `module { ... }` — so the dispatch call is unguarded.
            body = Program(structs=[], functions=[])
            while not self.match(TokenType.RBRACE, TokenType.EOF):
                self._parse_toplevel_decl(body)
                self.skip_newlines()

            self.expect(TokenType.RBRACE)

        return ModuleDecl(
            name=name_token.value,
            is_public=is_public,
            is_inline=is_inline,
            body=body,
            line=start.line,
            column=start.column
        )

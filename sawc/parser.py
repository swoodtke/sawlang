"""
Saw Language Parser
Recursive descent parser that builds an AST from tokens.
"""

from typing import List, Optional
from lexer import Token, TokenType
from ast_nodes import (
    Program, Function, Parameter, Block, Statement, Expression,
    LetStatement, AssignStatement, ReturnStatement, ExpressionStatement,
    IntLiteral, FloatLiteral, BoolLiteral, StringLiteral, Identifier,
    BinaryOp, UnaryOp, FunctionCall, IfExpr,
    TupleLiteral, TupleIndex, MemberAccess, StructInit,
    NoneLiteral, ForceUnwrap, NilCoalesce, OptionalChain,
    Struct, StructField,
    SawType, TypeKind
)


class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

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

    def parse(self) -> Program:
        structs = []
        functions = []
        self.skip_newlines()

        while not self.match(TokenType.EOF):
            if self.match(TokenType.STRUCT):
                structs.append(self.parse_struct())
            elif self.match(TokenType.FUNC):
                functions.append(self.parse_function())
            else:
                self.error(f"Expected struct or function declaration, got {self.current().type.name}")
            self.skip_newlines()

        return Program(structs=structs, functions=functions)

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
        elif token.type == TokenType.LPAREN:
            # Tuple type: (Type, Type, ...)
            self.advance()
            element_types = []
            if not self.match(TokenType.RPAREN):
                element_types.append(self.parse_type())
                while self.match(TokenType.COMMA):
                    self.advance()
                    element_types.append(self.parse_type())
            self.expect(TokenType.RPAREN)
            return SawType(TypeKind.TUPLE, element_types=element_types)
        elif token.type == TokenType.IDENT:
            # Struct type (user-defined)
            self.advance()
            return SawType(TypeKind.STRUCT, struct_name=token.value)
        else:
            self.error(f"Expected type, got {token.type.name}")

    def parse_function(self) -> Function:
        start = self.current()
        self.expect(TokenType.FUNC)

        name_token = self.expect(TokenType.IDENT, "Expected function name")
        name = name_token.value

        self.expect(TokenType.LPAREN)
        parameters = self.parse_parameters()
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
            line=start.line,
            column=start.column
        )

    def parse_struct(self) -> Struct:
        """Parse a struct declaration: struct Name { field: Type, ... }"""
        start = self.current()
        self.expect(TokenType.STRUCT)

        name_token = self.expect(TokenType.IDENT, "Expected struct name")
        name = name_token.value

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
            line=start.line,
            column=start.column
        )

    def parse_parameters(self) -> List[Parameter]:
        params = []

        if self.match(TokenType.RPAREN):
            return params

        while True:
            name_token = self.expect(TokenType.IDENT, "Expected parameter name")
            self.expect(TokenType.COLON, "Expected ':' after parameter name")
            param_type = self.parse_type()
            params.append(Parameter(name=name_token.value, type=param_type))

            if not self.match(TokenType.COMMA):
                break
            self.advance()  # consume comma

        return params

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
        elif self.match(TokenType.RETURN):
            return self.parse_return_statement()
        elif self.match(TokenType.IDENT) and self.peek(1).type == TokenType.ASSIGN:
            return self.parse_assign_statement()
        else:
            return self.parse_expression_statement()

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

    def parse_assign_statement(self) -> AssignStatement:
        name_token = self.advance()
        self.expect(TokenType.ASSIGN)
        value = self.parse_expression()

        return AssignStatement(
            name=name_token.value,
            value=value,
            line=name_token.line,
            column=name_token.column
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

    def parse_expression_statement(self) -> ExpressionStatement:
        expr = self.parse_expression()
        return ExpressionStatement(
            expression=expr,
            line=expr.line,
            column=expr.column
        )

    def parse_expression(self) -> Expression:
        return self.parse_nil_coalesce()

    def parse_nil_coalesce(self) -> Expression:
        """Parse nil coalescing: expr ?? default"""
        left = self.parse_comparison()

        while self.match(TokenType.DOUBLE_QUESTION):
            op_token = self.advance()
            right = self.parse_comparison()
            left = NilCoalesce(
                expr=left,
                default=right,
                line=op_token.line,
                column=op_token.column
            )

        return left

    def parse_comparison(self) -> Expression:
        left = self.parse_additive()

        while self.match(TokenType.EQ, TokenType.NEQ, TokenType.LT,
                         TokenType.GT, TokenType.LTE, TokenType.GTE):
            op_token = self.advance()
            right = self.parse_additive()
            left = BinaryOp(
                op=op_token.value,
                left=left,
                right=right,
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

        while self.match(TokenType.STAR, TokenType.SLASH):
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

        return self.parse_postfix()

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
                    # Member access: expr.field
                    self.advance()
                    expr = MemberAccess(
                        object=expr,
                        member=member_token.value,
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

        elif self.match(TokenType.STRING):
            self.advance()
            return StringLiteral(value=token.value, line=token.line, column=token.column)

        elif self.match(TokenType.IDENT):
            self.advance()
            # Check for function call or struct initialization
            if self.match(TokenType.LPAREN):
                # Peek ahead to see if this is struct init (name: value) or function call
                if self.peek(1).type == TokenType.IDENT and self.peek(2).type == TokenType.COLON:
                    return self.parse_struct_init(token)
                else:
                    return self.parse_function_call(token)
            return Identifier(name=token.value, line=token.line, column=token.column)

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

        else:
            self.error(f"Unexpected token: {token.type.name}")

    def parse_function_call(self, name_token: Token) -> FunctionCall:
        self.expect(TokenType.LPAREN)
        arguments = []

        if not self.match(TokenType.RPAREN):
            arguments.append(self.parse_expression())
            while self.match(TokenType.COMMA):
                self.advance()
                arguments.append(self.parse_expression())

        self.expect(TokenType.RPAREN)

        return FunctionCall(
            name=name_token.value,
            arguments=arguments,
            line=name_token.line,
            column=name_token.column
        )

    def parse_struct_init(self, name_token: Token) -> StructInit:
        """Parse struct initialization: StructName(field1: value1, field2: value2)"""
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
            line=name_token.line,
            column=name_token.column
        )

    def parse_if_expression(self) -> IfExpr:
        start = self.advance()  # consume 'if'
        condition = self.parse_expression()
        self.skip_newlines()
        then_branch = self.parse_block()

        else_branch = None
        self.skip_newlines()
        if self.match(TokenType.ELSE):
            self.advance()
            self.skip_newlines()
            else_branch = self.parse_block()

        return IfExpr(
            condition=condition,
            then_branch=then_branch,
            else_branch=else_branch,
            line=start.line,
            column=start.column
        )

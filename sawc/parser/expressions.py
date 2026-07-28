"""
Expression parsing methods for the Saw parser.

This module provides mixin methods for parsing expressions including:
- Operator precedence (nil coalesce, logical, comparison, range, arithmetic)
- Unary operators, casts, postfix operations
- Primary expressions (literals, identifiers, closures)
- Function calls, struct initialization
- Control flow expressions (if, match)
- Closure expressions

Usage:
    class Parser(ExpressionsMixin, ...):
        pass
"""

from typing import List, Optional
from lexer import TokenType
from ast_nodes import (
    Expression, Block, Statement,
    LetStatement, AssignStatement, ReturnStatement, ExpressionStatement,
    IntLiteral, FloatLiteral, BoolLiteral, StringLiteral, StringInterpolation, Identifier,
    BinaryOp, UnaryOp, MoveExpr, ReferenceExpr, CastExpr, FunctionCall, IfExpr, IfLetExpr,
    TupleLiteral, TupleIndex, ArrayLiteral, ArrayIndex,
    MemberAccess, StructInit,
    NoneLiteral, ForceUnwrap, NilCoalesce, OptionalChain,
    TryExpr, TryCatchExpr,
    RangeExpr, MatchExpr, MatchArm,
    MethodCall, SelfExpr,
    SawType, Argument,
    ClosureExpr, ClosureParam
)


class ExpressionsMixin:
    """Mixin providing expression parsing methods for Parser."""

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

        # `&+` / `&-` are the wrapping counterparts of `+` / `-` and share their
        # precedence tier (design 31).
        while self.match(TokenType.PLUS, TokenType.MINUS,
                         TokenType.WRAP_ADD, TokenType.WRAP_SUB):
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

        # `&*` is the wrapping counterpart of `*` and shares its precedence tier.
        while self.match(TokenType.STAR, TokenType.SLASH, TokenType.PERCENT,
                         TokenType.WRAP_MUL):
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

        if self.match(TokenType.AMPERSAND):
            # Reference expression at call site: &expr or &var expr
            ref_token = self.advance()

            # Check for &var expr (mutable reference)
            is_mutable = False
            if self.match(TokenType.VAR):
                is_mutable = True
                self.advance()

            operand = self.parse_unary()
            return ReferenceExpr(
                expr=operand,
                mutable=is_mutable,
                line=ref_token.line,
                column=ref_token.column
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
            # Convert escaped brace markers back to literal braces
            value = token.value.replace('\x01{', '{').replace('\x01}', '}')
            return StringLiteral(value=value, line=token.line, column=token.column)

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
            # `spawn { ... }` — the spawn intrinsic (design 21 item 5) is a call
            # with only a trailing closure and no parentheses. Restricted to the
            # `spawn` name so a bare `ident {` in other positions is never
            # mis-parsed as a call (it may open a block or struct-literal context).
            if (token.value == "spawn" and self.allow_trailing_closure
                    and self.match(TokenType.LBRACE)):
                trailing_closure = self._parse_closure_expression()
                return FunctionCall(
                    name=token.value,
                    arguments=[Argument(value=trailing_closure, name=None)],
                    type_args=type_args,
                    line=token.line, column=token.column
                )
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

        elif self.match(TokenType.TRY):
            return self.parse_try_expression()

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

    def parse_function_call(self, name_token, type_args: List[SawType] = None) -> FunctionCall:
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

    def parse_struct_init(self, name_token, type_args: Optional[List[SawType]] = None) -> StructInit:
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

    def parse_try_expression(self) -> Expression:
        """Parse try expression: try expr, try? expr, try! expr, or try { } catch { }

        Syntax variants:
        - try expr                  - propagate error (function must return Result)
        - try? expr                 - convert to optional (Result<T,E> -> T?)
        - try! expr                 - force unwrap (panic on error)
        - try expr catch { ... }    - inline catch handler
        - try { ... } catch { ... } - block try-catch
        """
        start = self.advance()  # consume 'try'

        # Check for try? or try!
        variant = "propagate"  # default
        if self.match(TokenType.QUESTION):
            self.advance()
            variant = "optional"
        elif self.match(TokenType.EXCLAIM):
            self.advance()
            variant = "force"

        self.skip_newlines()

        # Check if this is a try block: try { ... } catch { ... }
        if self.match(TokenType.LBRACE):
            # This is a try-catch block
            try_block = self.parse_block()
            self.skip_newlines()
            self.expect(TokenType.CATCH, "Expected 'catch' after try block")
            self.skip_newlines()
            catch_block = self.parse_block()
            return TryCatchExpr(
                try_block=try_block,
                catch_block=catch_block,
                error_binding=None,  # Default to 'error'
                line=start.line,
                column=start.column
            )

        # Single expression: try expr or try expr catch { ... }
        # Disable trailing closures so { doesn't get consumed as a trailing closure
        saved_trailing = self.allow_trailing_closure
        self.allow_trailing_closure = False
        expr = self.parse_expression()
        self.allow_trailing_closure = saved_trailing

        # Check for inline catch
        self.skip_newlines()
        if self.match(TokenType.CATCH):
            self.advance()
            self.skip_newlines()
            catch_block = self.parse_block()
            return TryExpr(
                expr=expr,
                variant=variant,
                catch_block=catch_block,
                line=start.line,
                column=start.column
            )

        return TryExpr(
            expr=expr,
            variant=variant,
            catch_block=None,
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
            # May start with a reference-capture marker: `&data` / `&var data`.
            if self.match(TokenType.AMPERSAND):
                self.advance()
                if self.match(TokenType.VAR):
                    self.advance()
            # Must then have an identifier (the first parameter name).
            if not self.match(TokenType.IDENT):
                return False

            # Scan ahead for 'in' keyword
            # Keep track of nesting for type annotations
            depth = 0
            just_saw_amp = False
            while True:
                token = self.current()
                if token.type == TokenType.EOF:
                    return False
                # A `}` at the outermost level ends the closure with no `in` seen
                # (not a param list). A `}` while nested closes an inner `{...}`
                # (e.g. a nested trailing closure) — decrement and keep scanning
                # so the inner closure's own `in` is not mistaken for ours.
                if token.type == TokenType.RBRACE:
                    if depth == 0:
                        return False
                    depth -= 1
                    self.advance()
                    continue
                if token.type == TokenType.IN and depth == 0:
                    return True
                if token.type in (TokenType.LT, TokenType.LPAREN, TokenType.LBRACE):
                    depth += 1
                if token.type == TokenType.GT or token.type == TokenType.RPAREN:
                    depth -= 1
                # A `var` immediately following `&` is a `&var data` ref param,
                # not a statement — don't treat it as a terminator there.
                if token.type == TokenType.AMPERSAND:
                    just_saw_amp = True
                    self.advance()
                    continue
                if token.type == TokenType.VAR and just_saw_amp:
                    just_saw_amp = False
                    self.advance()
                    continue
                just_saw_amp = False
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
            # Reference-capture params: `&data` (immutable borrow) or
            # `&var data` (mutable borrow) — the closure receives a pointer and
            # the body reads/mutates through it (design 21 item 3).
            is_reference = False
            reference_mutable = False
            if self.match(TokenType.AMPERSAND):
                self.advance()
                is_reference = True
                if self.match(TokenType.VAR):
                    self.advance()
                    reference_mutable = True

            param_token = self.expect(TokenType.IDENT, "Expected parameter name")

            # Check for optional type annotation
            type_ann = None
            if self.match(TokenType.COLON):
                self.advance()
                type_ann = self.parse_type()

            params.append(ClosureParam(
                name=param_token.value,
                type_annotation=type_ann,
                is_reference=is_reference,
                reference_mutable=reference_mutable,
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
            return self.parse_let_statement(mutable=False)
        elif self.match(TokenType.VAR):
            return self.parse_let_statement(mutable=True)
        elif self.match(TokenType.RETURN):
            start = self.current()
            self.advance()
            value = None
            if not self.match(TokenType.NEWLINE) and not self.match(TokenType.RBRACE):
                value = self.parse_expression()
            return ReturnStatement(value=value, line=start.line, column=start.column)
        elif self.match(TokenType.WHILE):
            return self.parse_while_statement()
        elif self.match(TokenType.FOR):
            return self.parse_for_statement()
        elif self.match(TokenType.BREAK):
            return self.parse_break_statement()
        elif self.match(TokenType.CONTINUE):
            return self.parse_continue_statement()
        else:
            # Assignment (`x = v`), compound assignment (`x += v`), or a bare
            # expression statement — closures mutate captured `&var` state.
            return self.parse_assignment_or_expression_statement()

    def _parse_interpolated_string(self, raw_value: str, line: int, column: int) -> StringInterpolation:
        """Parse a string with {expr} interpolations into parts and expressions.

        The raw_value contains the string with braces preserved, e.g. "Hello {name}!"
        Escaped braces are marked as \x01{ and \x01} by the lexer.
        Returns a StringInterpolation node with parts and expressions separated.
        """
        from lexer import Lexer

        parts = []
        expressions = []
        current_part = []
        i = 0

        while i < len(raw_value):
            # Check for escaped brace markers (\x01{ and \x01})
            if raw_value[i] == '\x01' and i + 1 < len(raw_value) and raw_value[i + 1] in '{}':
                # Convert marker back to literal brace
                current_part.append(raw_value[i + 1])
                i += 2
            elif raw_value[i] == '{':
                # Real interpolation start
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
        from .core import Parser

        try:
            sub_lexer = Lexer(expr_str)
            sub_tokens = sub_lexer.tokenize()
        except SyntaxError as e:
            # Provide better error message for interpolation failures
            preview = expr_str[:30] + "..." if len(expr_str) > 30 else expr_str
            raise SyntaxError(
                f"Invalid expression in string interpolation at {line}:{column}\n"
                f"  Expression: {{{preview}}}\n"
                f"  Error: {e}\n"
                f"  Hint: Use \\{{ and \\}} for literal braces in interpolated strings"
            )

        try:
            # Create a sub-parser with these tokens
            sub_parser = Parser(sub_tokens)
            return sub_parser.parse_expression()
        except SyntaxError as e:
            preview = expr_str[:30] + "..." if len(expr_str) > 30 else expr_str
            raise SyntaxError(
                f"Invalid expression in string interpolation at {line}:{column}\n"
                f"  Expression: {{{preview}}}\n"
                f"  Error: {e}\n"
                f"  Hint: Use \\{{ and \\}} for literal braces in interpolated strings"
            )

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

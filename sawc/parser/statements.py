"""
Statement parsing methods for the Saw parser.

This module provides mixin methods for parsing statements including blocks,
let/var bindings, assignments, control flow (while, for, break, continue),
guard statements, and return statements.

Usage:
    class Parser(StatementsMixin, ...):
        pass
"""

from lexer import TokenType
from ast_nodes import (
    Block, Statement,
    LetStatement, AssignStatement, CompoundAssignStatement, ReturnStatement, ExpressionStatement,
    GuardLetStatement, DestructuringLet, LendStatement,
    WhileExpr, ForLoop, BreakStatement, ContinueStatement,
    Identifier, MemberAccess, ArrayIndex, SelfExpr, TupleIndex,
    OptionalEvalExpr, OptionalChainAssign, ForceUnwrap, MethodCall
)

# Compound assignment token to operator mapping
COMPOUND_ASSIGN_OPS = {
    TokenType.PLUS_ASSIGN: '+',
    TokenType.MINUS_ASSIGN: '-',
    TokenType.STAR_ASSIGN: '*',
    TokenType.SLASH_ASSIGN: '/',
    TokenType.PERCENT_ASSIGN: '%',
    # Bitwise compound assignments (design 50).
    TokenType.AMP_ASSIGN: '&',
    TokenType.PIPE_ASSIGN: '|',
    TokenType.CARET_ASSIGN: '^',
    TokenType.SHL_ASSIGN: '<<',
    TokenType.SHR_ASSIGN: '>>',
}


class StatementsMixin:
    """Mixin providing statement parsing methods for Parser."""

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
        elif self.match(TokenType.LEND):
            return self.parse_lend_statement()
        elif self.match(TokenType.WHILE):
            return self.parse_while_statement()
        elif self.match(TokenType.FOR):
            return self.parse_for_statement()
        elif self.match(TokenType.BREAK):
            return self.parse_break_statement()
        elif self.match(TokenType.CONTINUE):
            return self.parse_continue_statement()
        elif self.match(TokenType.AT):
            # Attributes (design 58) are only legal on top-level func/static.
            self.error("attributes are not supported on local declarations")
        elif self.match_ident("static_assert") and self.peek(1).type == TokenType.LPAREN:
            # Compile-time assertion in statement position (design 53).
            return self.parse_static_assert()
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

        # Tuple pattern over an Optional tuple (design 63): `guard let (x, y) = ..`
        guard_pattern = None
        guard_name = ""
        if self.match(TokenType.LPAREN):
            guard_pattern = self.parse_pattern()
        else:
            name_token = self.expect(TokenType.IDENT, "Expected variable name after 'guard let/var'")
            guard_name = name_token.value
        self.expect(TokenType.ASSIGN, "Expected '=' in guard binding")
        # Disable trailing closures - guard is followed by else { }
        saved_trailing = self.allow_trailing_closure
        self.allow_trailing_closure = False
        optional_expr = self.parse_expression()
        # Design 111: `guard let _ = x?.y = v else { ... }` — an optional-chain
        # ASSIGNMENT (type `Void?`) consumed by the binding. The scrutinee is the
        # OptionalChainAssign, not the chain read.
        if self.match(TokenType.ASSIGN) and isinstance(optional_expr, OptionalEvalExpr):
            assign_tok = self.advance()
            value_expr = self.parse_expression()
            optional_expr = OptionalChainAssign(
                target=optional_expr, value=value_expr,
                line=assign_tok.line, column=assign_tok.column)
        self.allow_trailing_closure = saved_trailing

        self.skip_newlines()
        self.expect(TokenType.ELSE, "Expected 'else' in guard statement")
        self.skip_newlines()
        else_branch = self.parse_block()

        return GuardLetStatement(
            name=guard_name,
            optional_expr=optional_expr,
            mutable=mutable,
            else_branch=else_branch,
            line=start.line,
            column=start.column,
            pattern=guard_pattern,
        )

    def parse_let_statement(self, mutable: bool):
        start = self.advance()  # consume let/var

        # Tuple destructuring: `let (a, b) = ...` / `var (x, y) = ...`
        if self.match(TokenType.LPAREN):
            pattern = self.parse_pattern()
            self.expect(TokenType.ASSIGN, "Expected '=' in destructuring binding")
            value = self.parse_expression()
            return DestructuringLet(
                pattern=pattern,
                value=value,
                mutable=mutable,
                line=start.line,
                column=start.column,
            )

        name_token = self.expect(TokenType.IDENT, "Expected variable name")

        # `_` is a discard, not a binding (design 53 / DF1). `var _` has nothing
        # to mutate, so it is rejected.
        if name_token.value == "_" and mutable:
            self.error("`var _` is not allowed: `_` is a discard binding and has "
                       "nothing to mutate (use `let _` to evaluate and drop)")

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
        """Parse either an assignment (x = value, obj.field = value), compound assignment (x += 1), or expression statement."""
        start_pos = self.pos
        target_expr = self.parse_expression()

        # Optional-chain assignment `x?.y = v` / `x?.y += v` (design 111 +
        # design 227 unit 4): the target is an OptionalEvalExpr, and which
        # operator follows decides the OP, not whether the statement is a chain
        # assignment at all. Recognized ABOVE the plain/compound split, which is
        # where it used to sit on the plain branch only — so `o?.n += 5` was
        # "Invalid compound assignment target", a message about the shape of a
        # target that is fine (DF-225l). It becomes an OptionalChainAssign
        # expression (type `Void?`) wrapped in an ExpressionStatement —
        # statement position discards the `Void?` silently.
        if isinstance(target_expr, OptionalEvalExpr):
            chain_op = None
            chain_write = False
            if self.match(TokenType.ASSIGN):
                self.advance()  # consume '='
                chain_write = True
            elif self.current().type in COMPOUND_ASSIGN_OPS:
                chain_op = COMPOUND_ASSIGN_OPS[self.current().type]
                self.advance()  # consume the compound operator
                chain_write = True
            if chain_write:
                value_expr = self.parse_expression()
                return ExpressionStatement(
                    expression=OptionalChainAssign(
                        target=target_expr,
                        value=value_expr,
                        op=chain_op,
                        line=target_expr.line,
                        column=target_expr.column,
                    ),
                    line=target_expr.line,
                    column=target_expr.column,
                )

        # Check if this is a regular assignment
        if self.match(TokenType.ASSIGN):
            self.advance()  # consume '='
            value_expr = self.parse_expression()

            # Validate that target is assignable (Identifier, MemberAccess,
            # TupleIndex, ArrayIndex, or `self` — design 110 `&var self`
            # replacement). A tuple index is a place like any other projection
            # (DF-151j), so `t.0 = fresh` is the whole-element write.
            #
            # Design 176 adds the two PLACE spellings the grammar had not caught
            # up with. `m[k]! = v` (DF-146n) is the whole-value write through a
            # forced conditional lend — symmetric with `v[i] = fresh`, panicking
            # on an absent key — so a ForceUnwrap is a target. `c.slot(1) = 99`
            # (DF-175d) is the same write through a NAMED accessor, so a
            # MethodCall is one too; whether that call actually lends a place is
            # a question only the checker can answer, and it answers it with a
            # diagnostic naming the accessor.
            if not isinstance(target_expr, (Identifier, MemberAccess, ArrayIndex,
                                            TupleIndex, SelfExpr, ForceUnwrap,
                                            MethodCall)):
                self.error("Invalid assignment target")

            return AssignStatement(
                target=target_expr,
                value=value_expr,
                line=target_expr.line,
                column=target_expr.column,
            )

        # Check if this is a compound assignment (+=, -=, *=, /=, %=)
        current_type = self.current().type
        if current_type in COMPOUND_ASSIGN_OPS:
            op = COMPOUND_ASSIGN_OPS[current_type]
            self.advance()  # consume the compound operator
            value_expr = self.parse_expression()

            # Validate that target is assignable (Identifier, MemberAccess,
            # TupleIndex, ArrayIndex, or — design 176 — a place reached through
            # a forced conditional lend or a named accessor).
            if not isinstance(target_expr, (Identifier, MemberAccess, ArrayIndex,
                                            TupleIndex, ForceUnwrap, MethodCall)):
                self.error("Invalid compound assignment target")

            return CompoundAssignStatement(
                target=target_expr,
                op=op,
                value=value_expr,
                line=target_expr.line,
                column=target_expr.column,
            )

        # It's just an expression statement
        return ExpressionStatement(
            expression=target_expr,
            line=target_expr.line,
            column=target_expr.column
        )

    def parse_lend_statement(self) -> LendStatement:
        """`lend <place>` (design 141) — the borrow window of a borrows body.

        Deliberately shaped like `return` and deliberately not one: the
        function pauses here rather than finishing, and what follows the
        keyword names STORAGE rather than producing a value. A bare `lend` is
        rejected here so the "a place, not a value" error can be about the
        expression the author wrote.
        """
        start = self.advance()  # consume 'lend'

        if self.match(TokenType.NEWLINE, TokenType.RBRACE, TokenType.EOF):
            self.error("`lend` needs a place to lend — write `lend "
                       "self.buffer[i]` or `lend self.field`")

        place = self.parse_expression()
        return LendStatement(
            place=place,
            line=start.line,
            column=start.column
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

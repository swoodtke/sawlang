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
    OptionalEvalExpr, OptionalChainAssign, ForceUnwrap, MethodCall,
    IfLetExpr,
    LOCAL_ATTRIBUTES,
)

# Compound assignment token to operator mapping
COMPOUND_ASSIGN_OPS = {
    TokenType.PLUS_ASSIGN: '+',
    TokenType.MINUS_ASSIGN: '-',
    TokenType.STAR_ASSIGN: '*',
    TokenType.SLASH_ASSIGN: '/',
    TokenType.PERCENT_ASSIGN: '%',
    # Bitwise compound assignments.
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
        # Every statement gap runs through the separator chokepoint; this
        # first call covers the gap before the first statement.
        self.expect_statement_end()

        statements = []
        final_expr = None

        while not self.match(TokenType.RBRACE, TokenType.EOF):
            stmt_start = self.current()
            stmt = self.parse_statement()
            statements.append(stmt)
            self.expect_statement_end(stmt_start)

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
        # A local type alias is not legal. Without this check `type X = Y` in
        # a block falls through to the expression parser and reports
        # "undefined variable `type`", which describes the tokens, not the
        # mistake. `let type = ...` is unaffected.
        if self.at_type_alias_start():
            self.error(
                "a type alias may only be declared at module level, or as an "
                "associated type in a trait or extension body — not inside a "
                "function")
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
            # `@align(N)` ahead of a local `let`/`var` is the one attribute a
            # statement accepts; everything else is refused through the two
            # position funnels.
            return self._parse_attributed_local()
        elif self.match_ident("static_assert") and self.peek(1).type == TokenType.LPAREN:
            # Compile-time assertion in statement position.
            return self.parse_static_assert()
        else:
            # Try to parse assignment or expression statement
            # We need to parse the target expression first to handle both
            # simple assignments (x = value) and field assignments (obj.field = value)
            return self.parse_assignment_or_expression_statement()

    def _parse_attributed_local(self) -> Statement:
        """Parse an attribute block ahead of a local binding.

        Only `@align(N)` is legal here, and only on a `let`/`var` that binds one
        name: a destructuring `let` binds several and one alignment cannot say
        which, so it is refused rather than applied to the first.
        """
        at_token = self.current()
        at_pos = self.pos
        attrs = self.parse_attributes()
        self.skip_newlines()
        if not self.match(TokenType.LET, TokenType.VAR):
            # `_reject_attribute_position` reads the token after the `@` to
            # name the attribute, so wind back onto it. Nothing is re-parsed:
            # the call raises.
            self.pos = at_pos
            self._reject_attribute_position("this statement")
        self._reject_misplaced_attributes(attrs, LOCAL_ATTRIBUTES,
                                          "local declarations")
        stmt = self.parse_let_statement(mutable=self.match(TokenType.VAR))
        if not isinstance(stmt, LetStatement):
            self.error_at(
                at_token,
                "`@align` may not be written on a destructuring `let`: it "
                "binds several names and one alignment cannot say which of "
                "them it is about — bind them separately")
        stmt.attributes = attrs
        return stmt

    def parse_guard_statement(self) -> GuardLetStatement:
        start = self.advance()  # consume 'guard'

        # Expect 'let' or 'var'
        if not (self.match(TokenType.LET) or self.match(TokenType.VAR)):
            self.error("Expected 'let' or 'var' after 'guard'")

        mutable = self.current().type == TokenType.VAR
        self.advance()  # consume 'let' or 'var'

        # Tuple pattern over an Optional tuple: `guard let (x, y) = ..`
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
        # `guard let _ = x?.y = v else { ... }`: an optional-chain assignment
        # (type `Void?`) consumed by the binding. The scrutinee is the
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

        # `_` is a discard, not a binding. `var _` has nothing to mutate, so it
        # is rejected.
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

        # Optional-chain assignment `x?.y = v` / `x?.y += v`: the target is an
        # OptionalEvalExpr, and the operator that follows decides the op, not
        # whether this is a chain assignment. Recognized above the
        # plain/compound split so both spellings reach it. It becomes an
        # OptionalChainAssign (type `Void?`) wrapped in an ExpressionStatement,
        # which discards the `Void?`.
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

            # Validate that target is assignable: a variable, field, tuple
            # element or index, `self` (whole-referent replacement through
            # `&var self`), or a place reached through a lend. `m[k]! = v`
            # writes through a forced conditional lend (panicking on an absent
            # key); `c.slot(1) = 99` writes through a named accessor. Whether
            # that call really lends a place is the checker's question, and it
            # answers with a diagnostic naming the accessor (design 176).
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

            # Same targets as plain assignment, except `self`.
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
        """`lend <place>`, the borrow window of a borrows body (design 141).

        Shaped like `return` but not one: the function pauses here rather than
        finishing, and the operand names storage rather than producing a
        value. A bare `lend` is rejected here so the "a place, not a value"
        error can be about an expression the author wrote.
        """
        start = self.advance()  # consume 'lend'

        if self.at_statement_end():
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
        if not self.at_statement_end():
            value = self.parse_expression()

        return ReturnStatement(
            value=value,
            line=start.line,
            column=start.column
        )

    def parse_while_statement(self) -> WhileExpr:
        start = self.advance()  # consume 'while'

        # `while let x = SCRUT { ... }`. A condition never starts with
        # `let`/`var`, so no lookahead is needed.
        if self.match(TokenType.LET, TokenType.VAR):
            return self._parse_while_let(start)

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

    def _parse_while_let(self, start) -> WhileExpr:
        """`while let x = SCRUT { BODY }`, the drain loop (design 233).

        Lowered here into the constructs it means:

            while {
                if let x = SCRUT {
                    BODY
                } else { break }
            }

        The scrutinee sits inside the loop, so it re-evaluates every iteration
        and `continue` re-runs it. Because the node is an `if let`, every
        binding rule reaches it through the `if let` funnel
        (`_check_if_let_expr`) with no new position to keep in sync.

        Both halves are marked (`IfLetExpr.while_let`, `WhileExpr.is_while_let`)
        so diagnostics name `while let`, the synthesized `else { break }` is
        never reported as the author's branch, and value position is refusable.
        """
        mutable = self.current().type == TokenType.VAR
        self.advance()  # consume 'let' or 'var'

        # Tuple pattern over an Optional tuple, as `if let` takes one:
        # `while let (k, v) = pairs.pop()`.
        pattern = None
        name = ""
        if self.match(TokenType.LPAREN):
            pattern = self.parse_pattern()
        else:
            name_token = self.expect(
                TokenType.IDENT, "Expected variable name after 'while let/var'")
            name = name_token.value
        self.expect(TokenType.ASSIGN, "Expected '=' in optional binding")

        # Disable trailing closures — the `{` is the loop body.
        saved_trailing = self.allow_trailing_closure
        self.allow_trailing_closure = False
        optional_expr = self.parse_expression()
        self.allow_trailing_closure = saved_trailing

        self.skip_newlines()
        body = self.parse_block()

        # No `else` clause: the absent case is the loop exit. Report a written
        # `else` directly rather than as an unexpected token. Peek across
        # newlines and rewind, so a loop with no `else` keeps the statement
        # separator the caller expects.
        saved_pos = self.pos
        self.skip_newlines()
        if self.match(TokenType.ELSE):
            self.error("`while let` has no `else` clause — the loop exits when "
                       "the binding fails, so there is nothing for an `else` to "
                       "mean. Use `if let ... else` for a one-shot branch, or "
                       "put the exhausted case after the loop")
        self.pos = saved_pos

        binding = IfLetExpr(
            name=name,
            optional_expr=optional_expr,
            mutable=mutable,
            then_branch=body,
            else_branch=Block(
                statements=[BreakStatement(line=start.line,
                                           column=start.column)],
                final_expr=None, line=start.line, column=start.column),
            line=start.line,
            column=start.column,
            pattern=pattern,
            while_let=True,
        )
        return WhileExpr(
            condition=None,
            body=Block(
                statements=[ExpressionStatement(
                    expression=binding, line=start.line, column=start.column)],
                final_expr=None, line=start.line, column=start.column),
            line=start.line,
            column=start.column,
            is_while_let=True,
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
        if not self.at_statement_end():
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

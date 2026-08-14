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
    LetStatement, AssignStatement, CompoundAssignStatement, ReturnStatement, ExpressionStatement,
    IntLiteral, FloatLiteral, BoolLiteral, StringLiteral, StringInterpolation,
    FormatPlaceholder, Identifier,
    BinaryOp, UnaryOp, MoveExpr, ReferenceExpr, CastExpr, FunctionCall, IfExpr, IfLetExpr,
    TupleLiteral, TupleIndex, ArrayLiteral, ArrayIndex,
    MapLiteral, SetLiteral,
    MemberAccess, StructInit,
    NoneLiteral, SourceLocationLiteral, LendVarLiteral,
    ForceUnwrap, NilCoalesce, OptionalChain,
    BindOptional, OptionalEvalExpr, OptionalChainAssign,
    TryExpr, TryCatchExpr,
    RangeExpr, MatchExpr, MatchArm,
    MethodCall, SelfExpr,
    SawType, Argument,
    ClosureExpr, ClosureParam,
    Pattern, WildcardPattern, BindingPattern, LiteralPattern,
    RangePattern, TuplePattern, EnumPattern,
)
from .types import CommittedGenericError


class ExpressionsMixin:
    """Mixin providing expression parsing methods for Parser."""

    def parse_expression(self) -> Expression:
        # design 130 removed the line-level `unsafe <expr>` marker: `unsafe` is a
        # DECLARATION modifier and a function-type effect now, never an expression
        # prefix. A stray one here reaches `parse_primary` and is reported as a
        # token that cannot begin an expression.
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
        left = self.parse_bitor()

        while self.match(TokenType.AND):
            op_token = self.advance()
            right = self.parse_bitor()
            left = BinaryOp(
                op='&&',
                left=left,
                right=right,
                line=op_token.line,
                column=op_token.column
            )

        return left

    # Bitwise tiers (design 50), C-family: `&` binds tighter than `^`, which
    # binds tighter than `|`; all three sit between logical `&&` and the
    # comparison operators. Integer-only — enforced by the typechecker.

    def parse_bitor(self) -> Expression:
        """Parse bitwise OR: expr | expr"""
        left = self.parse_bitxor()

        while self.match(TokenType.PIPE):
            op_token = self.advance()
            right = self.parse_bitxor()
            left = BinaryOp(op='|', left=left, right=right,
                            line=op_token.line, column=op_token.column)

        return left

    def parse_bitxor(self) -> Expression:
        """Parse bitwise XOR: expr ^ expr"""
        left = self.parse_bitand()

        while self.match(TokenType.CARET):
            op_token = self.advance()
            right = self.parse_bitand()
            left = BinaryOp(op='^', left=left, right=right,
                            line=op_token.line, column=op_token.column)

        return left

    def parse_bitand(self) -> Expression:
        """Parse bitwise AND: expr & expr.

        The infix `&` is disambiguated from its three other meanings purely by
        recursive-descent position: a *prefix* `&x` / `&var x` (call-site
        reference) is consumed by `parse_unary` as part of the left operand, and
        the wrapping ops `&+ &- &*` are distinct single tokens (WRAP_*), never
        AMPERSAND. So an AMPERSAND reaching this loop is always the binary
        bitwise-AND operator, sitting in infix position after a full left operand.
        """
        left = self.parse_comparison()

        while self.match(TokenType.AMPERSAND):
            op_token = self.advance()
            right = self.parse_comparison()
            left = BinaryOp(op='&', left=left, right=right,
                            line=op_token.line, column=op_token.column)

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
        left = self.parse_shift()

        if self.match(TokenType.DOTDOT, TokenType.DOTDOT_EQ):
            op_token = self.advance()
            right = self.parse_shift()
            return RangeExpr(
                start=left,
                end=right,
                line=op_token.line,
                column=op_token.column,
                is_inclusive=(op_token.type == TokenType.DOTDOT_EQ)
            )

        return left

    def parse_shift(self) -> Expression:
        """Parse bit shifts `<< >>` (design 50), tighter than comparison but
        looser than `+ -` (C-family: `x << 2 + 1` == `x << (2 + 1)`).

        The lexer keeps bare `<`/`>` as individual tokens so nested generic
        closings (`Vector<Box<Int>>`) are unaffected; here in expression position
        two *immediately adjacent* `<<` or `>>` tokens are combined into a shift.
        Adjacency (no interior whitespace) keeps `a < b` / `a > b` comparisons
        and a spaced `a > > b` from ever being read as a shift.
        """
        left = self.parse_additive()

        while True:
            tok = self.current()
            nxt = self.peek(1)
            if (tok.type == TokenType.LT and nxt.type == TokenType.LT
                    and self._tokens_adjacent(tok, nxt)):
                self.advance()
                self.advance()
                right = self.parse_additive()
                left = BinaryOp(op='<<', left=left, right=right,
                                line=tok.line, column=tok.column)
            elif (tok.type == TokenType.GT and nxt.type == TokenType.GT
                    and self._tokens_adjacent(tok, nxt)):
                self.advance()
                self.advance()
                right = self.parse_additive()
                left = BinaryOp(op='>>', left=left, right=right,
                                line=tok.line, column=tok.column)
            else:
                break

        return left

    @staticmethod
    def _tokens_adjacent(a, b) -> bool:
        """True if token `b` immediately follows `a` with no whitespace between."""
        return a.line == b.line and b.column == a.column + 1

    @staticmethod
    def _decode_int_literal(text: str) -> int:
        """Decode an INT token's canonical text (prefix kept, underscores already
        stripped by the lexer) into its integer value (design 50)."""
        low = text[:2].lower()
        if low == '0x':
            return int(text, 16)
        if low == '0b':
            return int(text, 2)
        if low == '0o':
            return int(text, 8)
        return int(text, 10)

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

        if self.match(TokenType.STAR):
            # PREFIX `*` — pointer dereference, DESUGARED HERE (design 219's
            # wave-B rider). `*p` becomes exactly the place `p[0]` already
            # names, so nothing downstream learns a new node kind: the
            # typechecker, the place machinery and codegen all see the pointer
            # place they have always handled, and `move *p`, `*p = v`,
            # `(*p).field` and a `&*p` argument each work because the SAME
            # production is behind them.
            #
            # Disambiguated by POSITION exactly as unary `-` is: the binary
            # parser consumes its own `*` before descending here, so a leading
            # `*` can only be a prefix. This is not a general user-definable
            # prefix operator — that surface stays closed.
            #
            # `p[0]` conflates array indexing with single-pointee deref; std's
            # pointer sites are mostly single-object, where `*slot` states the
            # intent. The SPAN is the `*` token's, so every diagnostic anchors
            # on what the author wrote (the elaboration principle's invariant).
            star_token = self.advance()
            operand = self.parse_unary()
            return ArrayIndex(
                array_expr=operand,
                index=IntLiteral(value=0, line=star_token.line,
                                 column=star_token.column),
                line=star_token.line,
                column=star_token.column
            )

        if self.match(TokenType.TILDE):
            # Unary bitwise complement `~x` (design 50); integer-only, enforced
            # by the typechecker.
            op_token = self.advance()
            operand = self.parse_unary()
            return UnaryOp(
                op='~',
                operand=operand,
                line=op_token.line,
                column=op_token.column
            )

        if self.match(TokenType.MOVE):
            move_token = self.advance()
            # `move *p` — the prefix-deref spelling of `move p[0]`, and the
            # fourth move-out family member in its most readable form (wave A
            # legalized the transfer; the rider gives it this spelling). The
            # star is consumed HERE rather than by the prefix arm above because
            # `move` parses its own path: the projection loop below builds the
            # place, and this just seeds it with the `[0]` hop.
            deref_star = None
            if self.match(TokenType.STAR):
                deref_star = self.advance()
            # move must be followed by an identifier (the root binding)
            if not self.match(TokenType.IDENT):
                raise SyntaxError(f"Expected identifier after 'move' at line {move_token.line}")
            base_token = self.advance()
            # Consume any member/tuple/index projections so a partial move like
            # `move p.x`, `move p.x.y`, or `move arr[i]` parses cleanly. Partial
            # moves are forbidden (design 35); the typechecker rejects the path
            # with a diagnostic naming the field and base. Accepting the syntax
            # here avoids a bare parse error (`move p.x`) or silent mis-handling
            # (`move arr[i]` used to drop the index).
            node = Identifier(name=base_token.value, line=base_token.line,
                              column=base_token.column)
            is_partial = False
            if deref_star is not None:
                node = ArrayIndex(
                    array_expr=node,
                    index=IntLiteral(value=0, line=deref_star.line,
                                     column=deref_star.column),
                    line=deref_star.line, column=deref_star.column)
                is_partial = True
            while True:
                if self.match(TokenType.DOT):
                    dot = self.advance()
                    member = self.current()
                    if member.type == TokenType.INT:
                        self.advance()
                        node = TupleIndex(tuple_expr=node, index=int(member.value),
                                          line=dot.line, column=dot.column)
                    elif member.type == TokenType.IDENT:
                        self.advance()
                        node = MemberAccess(object=node, member=member.value,
                                            line=dot.line, column=dot.column)
                    else:
                        self.error("Expected field name or tuple index after '.'")
                    is_partial = True
                elif self.match(TokenType.LBRACKET):
                    bracket = self.advance()
                    index_expr = self.parse_expression()
                    self.expect(TokenType.RBRACKET, "Expected ']' after index in move")
                    node = ArrayIndex(array_expr=node, index=index_expr,
                                      line=bracket.line, column=bracket.column)
                    is_partial = True
                else:
                    break
            # design 131: a trailing `!` makes this `move o!` — the move at an
            # optional projection. Consumed here (rather than left to the
            # postfix parser) so the whole thing stays ONE MoveExpr: the move
            # retires the binding `o`, and the `!` only picks the payload out of
            # the value it yields.
            unwrap = False
            if self.match(TokenType.EXCLAIM):
                self.advance()
                unwrap = True
            return MoveExpr(
                variable=base_token.value,
                path=node if is_partial else None,
                unwrap=unwrap,
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
            # `x as Int? ?? y` is a cast followed by the coalescing operator,
            # not a cast to `Int???`. This is the only place the type grammar
            # and the expression grammar meet at a `??` (DF-174c) — everywhere
            # else a type is followed by `=`, `,`, `)`, `>`, `{` or a newline.
            target_type = self.parse_type(allow_nested_optional=False)
            expr = CastExpr(
                expr=expr,
                target_type=target_type,
                line=as_token.line,
                column=as_token.column
            )

        return expr

    def _parse_dot_access(self, base_expr: Expression, dot_token, member_name: str) -> Expression:
        """Build a `.member` / `.method(args)` access on `base_expr` (design 111
        shares this between plain `.` and the `?.` optional hop). `member_name` is
        already consumed; this handles explicit `<...>` type args, a `(args)` call,
        a trailing-closure call, or a bare field access."""
        # Explicit method-level type arguments (brief 36):
        # `v.map<Int>(...)` or the trailing-closure form
        # `v.map<Int> { ... }`. Same backtracking ambiguity as a free
        # generic call — keep the `<...>` only if it is genuinely
        # followed by `(` (a paren call) or `{` (a trailing-closure
        # call); otherwise `a.b < c` is a comparison and we restore.
        method_type_args = None
        if self.match(TokenType.LT):
            saved_pos = self.pos
            try:
                method_type_args = self._parse_type_args()
                followed_by_call = self.match(TokenType.LPAREN) or (
                    self.allow_trailing_closure and self.match(TokenType.LBRACE))
                if not followed_by_call:
                    self.pos = saved_pos
                    method_type_args = None
            except CommittedGenericError:
                # A committed generic list that is ill-formed — a trailing comma
                # (design 129) or a reference argument (DF-163d). Report it
                # rather than backtracking into a nonsense comparison.
                raise
            except SyntaxError:
                self.pos = saved_pos
                method_type_args = None

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

            return MethodCall(
                object=base_expr,
                method_name=member_name,
                arguments=arguments,
                type_args=method_type_args,
                line=dot_token.line,
                column=dot_token.column
            )
        elif self.allow_trailing_closure and self.match(TokenType.LBRACE):
            # Method call with only trailing closure: obj.method { ... }
            # (possibly with explicit type args: obj.method<U> { ... })
            trailing_closure = self._parse_closure_expression()
            arguments = [Argument(value=trailing_closure, name=None)]
            return MethodCall(
                object=base_expr,
                method_name=member_name,
                arguments=arguments,
                type_args=method_type_args,
                line=dot_token.line,
                column=dot_token.column
            )
        else:
            # It's just member access (could be simple enum variant or struct field)
            # For simple enum variants like Status.Success, we create MemberAccess
            # The type checker will convert this to EnumInit if needed
            return MemberAccess(
                object=base_expr,
                member=member_name,
                line=dot_token.line,
                column=dot_token.column
            )

    def parse_postfix(self) -> Expression:
        expr = self.parse_primary()

        # `saw_chain` is True while an optional-chain postfix run is open (design
        # 111): a `?.` opens it; further `.`/`?.` extend it; `!`, `[`, and a tuple
        # `.N` CLOSE it (wrapping the run in an OptionalEvalExpr) so they apply to
        # the resulting Optional — `a?.b!` is `(a?.b)!`. One short-circuit skips the
        # whole run.
        saw_chain = False

        def _close_chain():
            nonlocal expr, saw_chain
            if saw_chain:
                expr = OptionalEvalExpr(expr=expr, line=expr.line, column=expr.column)
                saw_chain = False

        # Handle postfix operations: .0, .1, .field, !, ?., [i]
        while True:
            if self.match(TokenType.DOT):
                dot_token = self.advance()
                member_token = self.current()

                if member_token.type == TokenType.INT:
                    # Tuple indexing: expr.0, expr.1, etc.
                    _close_chain()
                    self.advance()
                    index = int(member_token.value)
                    expr = TupleIndex(
                        tuple_expr=expr,
                        index=index,
                        line=dot_token.line,
                        column=dot_token.column
                    )
                elif member_token.type == TokenType.IDENT:
                    # Could be member access or method/enum call; extends an open
                    # optional chain (operates on the unwrapped payload).
                    member_name = member_token.value
                    self.advance()
                    expr = self._parse_dot_access(expr, dot_token, member_name)
                else:
                    # Design 161: the number scanner no longer swallows a dot that
                    # no digit follows (which is what broke `7.to_string()`), so a
                    # trailing-dot float now arrives here as INT + DOT. Teach the
                    # spelling instead of reporting a bare "got NEWLINE".
                    if isinstance(expr, IntLiteral):
                        self.error(
                            f"Expected field name or tuple index after '.', got "
                            f"{member_token.type.name} — a float literal needs a "
                            f"digit after the point (write `{expr.value}.0`)")
                    self.error(f"Expected field name or tuple index after '.', got {member_token.type.name}")

            elif self.match(TokenType.EXCLAIM):
                # Force unwrap: expr! — closes an open chain, then unwraps it.
                exclaim_token = self.advance()
                _close_chain()
                expr = ForceUnwrap(
                    expr=expr,
                    line=exclaim_token.line,
                    column=exclaim_token.column
                )

            elif self.match(TokenType.QUESTION_DOT):
                # Optional chaining hop: expr?.member / expr?.method(args).
                chain_token = self.advance()
                member_token = self.expect(TokenType.IDENT, "Expected member name after '?.'")
                base = BindOptional(
                    expr=expr, line=chain_token.line, column=chain_token.column)
                expr = self._parse_dot_access(base, chain_token, member_token.value)
                saw_chain = True

            elif self.match(TokenType.LBRACKET):
                # Array indexing: expr[index] — closes an open chain first
                # (`?.` indexing is out of scope; `a?.b[i]` is `(a?.b)[i]`).
                bracket_token = self.advance()
                _close_chain()
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

        _close_chain()
        return expr

    def parse_primary(self) -> Expression:
        token = self.current()

        if self.match(TokenType.INT):
            self.advance()
            return IntLiteral(value=self._decode_int_literal(token.value),
                              line=token.line, column=token.column,
                              suffix=token.suffix)

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

        elif self.match(TokenType.HASH_DIRECTIVE):
            # `#file` / `#line` / `#function` source-location literal (design 98).
            # The source file is stamped here (definition site: the file the
            # token appears in); the typechecker resolves the value from the
            # token's own line + enclosing-function context. `source_file` is ""
            # for an interpolation sub-parser lacking it — the enclosing string
            # token's file, threaded through `_parse_expression_from_string`.
            self.advance()
            if token.value == 'lend_var':
                # `#lend_var` (design 179) is the other magic literal: it names
                # the SPECIALIZATION a `borrows` body is being compiled as, not
                # anything about the source position, so it carries no payload.
                return LendVarLiteral(line=token.line, column=token.column)
            return SourceLocationLiteral(
                kind=token.value,
                source_file=(self.source_file or None),
                line=token.line, column=token.column)

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
                except CommittedGenericError:
                    # A committed generic list that is ill-formed — a trailing
                    # comma (design 129) or a reference argument (DF-163d).
                    # Report it rather than backtracking into a comparison.
                    raise
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

            # Named tuple literal (design 63): `(x: 3, y: 4)`. A leading `IDENT :`
            # (inside a grouping/tuple paren — NOT a call's argument list) begins
            # one. All-or-nothing labeling is enforced per element.
            if (self.current().type == TokenType.IDENT
                    and self.peek(1).type == TokenType.COLON):
                field_names = []
                elements = []
                while True:
                    if not (self.current().type == TokenType.IDENT
                            and self.peek(1).type == TokenType.COLON):
                        self.error("named tuple literal must label every element "
                                   "(all-or-nothing)")
                    field_names.append(self.advance().value)
                    self.advance()  # consume ':'
                    elements.append(self.parse_expression())
                    if self.match(TokenType.COMMA):
                        self.advance()
                        if self.match(TokenType.RPAREN):
                            break
                        continue
                    break
                self.expect(TokenType.RPAREN, "Expected ')' after named tuple")
                return TupleLiteral(elements=elements, field_names=field_names,
                                    line=start.line, column=start.column)

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
            # Array literal: [1, 2, 3] — or the REPEAT literal [v; N] (design
            # 148), N copies of one value. The `;` after the first element is
            # what tells them apart, and it can mean nothing else inside `[ ]`,
            # so no lookahead or backtracking is needed. It reads like the array
            # TYPE it produces: `[0; 256]` has type `[Int; 256]`.
            start = self.current()
            self.advance()  # consume '['

            elements = []
            repeat_count = None
            if not self.match(TokenType.RBRACKET):
                elements.append(self.parse_expression())
                if self.match(TokenType.SEMICOLON):
                    self.advance()
                    repeat_count = self.parse_expression()
                else:
                    while self.match(TokenType.COMMA):
                        self.advance()
                        # Allow trailing comma
                        if self.match(TokenType.RBRACKET):
                            break
                        elements.append(self.parse_expression())

            self.expect(TokenType.RBRACKET, "Expected ']' after array elements")
            return ArrayLiteral(elements=elements, repeat_count=repeat_count,
                                line=start.line, column=start.column)

        elif self.match(TokenType.LBRACE):
            # A `{` opens a closure/block, a map literal `{k: v}` / `{:}`, or a
            # set literal `{a, b, ...}` (design 54). Bounded lookahead (no
            # backtracking) picks which; `{}` and `{expr}` are ALWAYS a
            # closure/block, and `{ x in ... }` closure params are unambiguous.
            kind = self._classify_brace_literal()
            if kind == 'map':
                return self._parse_map_literal()
            elif kind == 'set':
                return self._parse_set_literal()
            # Closure expression: { x in x * 2 } or { $0 * 2 }
            return self._parse_closure_expression()

        elif self.match(TokenType.DOLLAR_PARAM):
            # Shorthand parameter reference outside of closure (will be validated by typechecker)
            param_token = self.current()
            self.advance()
            return Identifier(name=param_token.value, line=param_token.line, column=param_token.column)

        elif self.match(TokenType.UNSAFE):
            # design 130 removed design 81's line-level marker. Saw code written
            # against the old model puts `unsafe` in front of a pointer
            # expression, and a bare "unexpected token" would leave the reader to
            # work out that the whole model changed under them.
            self.error("`unsafe` is not an expression prefix — mark the "
                       "enclosing declaration instead (`func f(...) unsafe`), "
                       "and delete the marker here")

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
        else:
            # Positional argument
            value = self.parse_expression()
            name = None
        # A `&`/`&var` reference at the top of an argument is the one legal
        # position for a reference (design 34). Mark it so the typechecker can
        # reject `&var` used anywhere else.
        if isinstance(value, ReferenceExpr):
            value.in_argument_position = True
        return Argument(value=value, name=name)

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

        # Design 66: a trailing closure after `name(label: value, ...)` is an
        # unambiguous FUNCTION call (structs never take trailing closures). The
        # `IDENT COLON` lookahead routed us here, but with a trailing `{` this is
        # a fully-labeled call — build a FunctionCall (labeled args + the closure
        # bound to the last parameter) so the typechecker resolves it as a call.
        if self.allow_trailing_closure and self.match(TokenType.LBRACE):
            trailing_closure = self._parse_closure_expression()
            args = []
            for (n, v) in field_inits:
                if isinstance(v, ReferenceExpr):
                    v.in_argument_position = True
                args.append(Argument(value=v, name=n))
            args.append(Argument(value=trailing_closure, name=None))
            return FunctionCall(
                name=name_token.value,
                arguments=args,
                type_args=type_args,
                line=name_token.line,
                column=name_token.column
            )

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

            # Tuple pattern over an Optional tuple (design 63): `if let (x, y) = ..`
            iflet_pattern = None
            iflet_name = ""
            if self.match(TokenType.LPAREN):
                iflet_pattern = self.parse_pattern()
            else:
                name_token = self.expect(TokenType.IDENT, "Expected variable name after 'if let/var'")
                iflet_name = name_token.value
            self.expect(TokenType.ASSIGN, "Expected '=' in optional binding")
            # Disable trailing closures - the { is part of the if block
            saved_trailing = self.allow_trailing_closure
            self.allow_trailing_closure = False
            optional_expr = self.parse_expression()
            # Design 111: `if let _ = x?.y = v { ... }` — an optional-chain
            # ASSIGNMENT (type `Void?`) consumed by the binding.
            if self.match(TokenType.ASSIGN) and isinstance(optional_expr, OptionalEvalExpr):
                assign_tok = self.advance()
                optional_assign_value = self.parse_expression()
                optional_expr = OptionalChainAssign(
                    target=optional_expr, value=optional_assign_value,
                    line=assign_tok.line, column=assign_tok.column)
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
                name=iflet_name,
                optional_expr=optional_expr,
                mutable=mutable,
                then_branch=then_branch,
                else_branch=else_branch,
                line=start.line,
                column=start.column,
                pattern=iflet_pattern,
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

            # Parse the arm pattern (design 63 T1d: literals, ranges, tuples,
            # bindings, and the classic enum-variant form).
            pattern = self.parse_pattern()

            # Optional guard: `case <pattern> if <cond> ->`
            guard = None
            if self.match(TokenType.IF):
                self.advance()
                saved_tc = self.allow_trailing_closure
                self.allow_trailing_closure = False
                guard = self.parse_expression()
                self.allow_trailing_closure = saved_tc

            # Derive the legacy variant_name/bindings for the classic enum-switch
            # lowering when the pattern is a plain enum-variant/wildcard with only
            # binding/wildcard subpatterns (design 61 path stays byte-identical).
            variant_name, bindings = self._legacy_arm_shape(pattern)

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
                column=arm_start.column,
                pattern=pattern,
                guard=guard,
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

    def _legacy_arm_shape(self, pattern: 'Pattern'):
        """Derive the legacy (variant_name, bindings) from a pattern when it is a
        plain enum-variant / wildcard so the classic enum-switch lowering keeps
        working unchanged. Returns ("", []) for pattern forms the general
        if-chain lowering owns (literals, ranges, tuples, bare bindings, or an
        enum pattern whose subpatterns are not all plain bindings)."""
        if isinstance(pattern, WildcardPattern):
            return "_", []
        if isinstance(pattern, EnumPattern):
            names = []
            for sub in pattern.subpatterns:
                if isinstance(sub, WildcardPattern):
                    names.append("_")
                elif isinstance(sub, BindingPattern):
                    names.append(sub.name)
                else:
                    return "", []  # a nested non-binding subpattern -> general path
            return pattern.variant_name, names
        return "", []

    def _parse_int_pattern_literal(self):
        """Parse an integer literal endpoint in a pattern, allowing a leading
        `-` for negatives. Returns the literal expression."""
        if self.match(TokenType.MINUS):
            self.advance()
            tok = self.expect(TokenType.INT, "Expected integer after '-' in pattern")
            lit = self._make_int_literal(tok)
            return UnaryOp(op='-', operand=lit, line=tok.line, column=tok.column)
        tok = self.expect(TokenType.INT, "Expected integer literal in pattern")
        return self._make_int_literal(tok)

    def _make_int_literal(self, tok):
        """Build an IntLiteral from an INT token (mirrors primary-expr parsing,
        honoring a fixed-width suffix)."""
        return IntLiteral(
            value=self._decode_int_literal(tok.value),
            suffix=getattr(tok, 'suffix', None),
            line=tok.line,
            column=tok.column,
        )

    def parse_pattern(self) -> 'Pattern':
        """Parse one match-arm pattern (design 63 T1d)."""
        tok = self.current()

        # Tuple pattern: `(p0, p1, ...)`
        if self.match(TokenType.LPAREN):
            self.advance()

            def _named_pattern_check():
                # The NAMED pattern form `(x: a, y: b)` is deferred (design 63) —
                # reject it cleanly rather than positional-parse into confusion.
                if (self.current().type == TokenType.IDENT
                        and self.peek(1).type == TokenType.COLON):
                    self.error("named tuple patterns (`(x: a)`) are not supported "
                               "yet; use positional destructuring (`(a, b)`)")

            elements = []
            if not self.match(TokenType.RPAREN):
                _named_pattern_check()
                elements.append(self.parse_pattern())
                while self.match(TokenType.COMMA):
                    self.advance()
                    _named_pattern_check()
                    elements.append(self.parse_pattern())
            self.expect(TokenType.RPAREN, "Expected ')' to close tuple pattern")
            return TuplePattern(elements=elements, line=tok.line, column=tok.column)

        # Integer literal / range: `0`, `-5`, `1..9`, `1..=9`
        if self.match(TokenType.INT) or self.match(TokenType.MINUS):
            start_lit = self._parse_int_pattern_literal()
            if self.match(TokenType.DOTDOT, TokenType.DOTDOT_EQ):
                inclusive = self.current().type == TokenType.DOTDOT_EQ
                self.advance()
                end_lit = self._parse_int_pattern_literal()
                return RangePattern(start=start_lit, end=end_lit,
                                    is_inclusive=inclusive,
                                    line=tok.line, column=tok.column)
            return LiteralPattern(value=start_lit, line=tok.line, column=tok.column)

        # String literal pattern
        if self.match(TokenType.STRING):
            self.advance()
            return LiteralPattern(value=StringLiteral(value=tok.value, line=tok.line, column=tok.column),
                                  line=tok.line, column=tok.column)

        # Bool literal pattern
        if self.match(TokenType.TRUE, TokenType.FALSE):
            self.advance()
            return LiteralPattern(value=BoolLiteral(value=(tok.type == TokenType.TRUE),
                                                    line=tok.line, column=tok.column),
                                  line=tok.line, column=tok.column)

        # Identifier: wildcard `_`, enum variant, or bare binding.
        ident = self.expect(TokenType.IDENT, "Expected a pattern after 'case'")
        name = ident.value
        if name == "_":
            return WildcardPattern(line=ident.line, column=ident.column)
        # An enum-variant pattern is a capitalized identifier, or any identifier
        # immediately followed by `(` (a payload pattern). A lowercase bare
        # identifier is a binding.
        is_variant = (name[:1].isupper()) or self.match(TokenType.LPAREN)
        if is_variant:
            subpatterns = []
            if self.match(TokenType.LPAREN):
                self.advance()
                if not self.match(TokenType.RPAREN):
                    subpatterns.append(self.parse_pattern())
                    while self.match(TokenType.COMMA):
                        self.advance()
                        subpatterns.append(self.parse_pattern())
                self.expect(TokenType.RPAREN, "Expected ')' to close variant pattern")
            return EnumPattern(variant_name=name, subpatterns=subpatterns,
                               line=ident.line, column=ident.column)
        return BindingPattern(name=name, line=ident.line, column=ident.column)

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

    # === Collection Literals (design 54) ===

    def _classify_brace_literal(self) -> str:
        """Bounded lookahead from `{` deciding 'map', 'set', or 'closure'.

        Rules (design 54, NO type feedback):
          - `{:}`                              -> map (empty)
          - first depth-0 delimiter is `:`     -> map literal
          - first depth-0 delimiter is `,`     -> set literal
          - `{}`, `{expr}`, `{ x in ... }`, `{ [caps] ... }` -> closure/block

        Closure params (`x in`, `x, y in`, `x: T in`) are detected FIRST so
        their `,`/`:` are never mistaken for collection delimiters. The scan is
        bounded — it peeks to the first depth-0 `:`/`,`/`}`/`in` after the
        opening expression and never backtracks (the hot parse path)."""
        saved = self.pos
        try:
            self.advance()  # consume '{'
            self.skip_newlines()
            # `{}` empty block/closure.
            if self.match(TokenType.RBRACE):
                return 'closure'
            # `{:}` empty map — the only construct that starts with a colon.
            if self.match(TokenType.COLON):
                return 'map'
            # A bracketed capture list `{ [caps] ... in ... }` => closure.
            if self.match(TokenType.LBRACKET) and self._closure_capture_list_ahead():
                return 'closure'
            # Closure params (`x in`, `x, y in`, `x: Type in`) => closure.
            if self._is_closure_with_named_params():
                return 'closure'
            # Scan the leading expression to its first depth-0 delimiter.
            depth = 0
            while True:
                t = self.current()
                if t.type == TokenType.EOF:
                    return 'closure'
                if depth == 0:
                    if t.type == TokenType.COLON:
                        return 'map'
                    if t.type == TokenType.COMMA:
                        return 'set'
                    if t.type == TokenType.RBRACE:
                        return 'closure'   # `{expr}` single expression -> block
                    if t.type == TokenType.IN:
                        return 'closure'   # defensive (params handled above)
                    if t.type in (TokenType.SEMICOLON, TokenType.LET, TokenType.VAR,
                                  TokenType.RETURN, TokenType.BREAK, TokenType.CONTINUE,
                                  TokenType.ASSIGN):
                        return 'closure'   # a statement body -> block
                # NOTE: `<`/`>` are deliberately NOT treated as depth brackets
                # (design 59 E2). They are ambiguous — a comparison (`a > 0`) or a
                # generic-arg bracket (`Map<K, V>`) — and treating them as depth
                # made an unparenthesized comparison element (`{a > 0, b > 0}`)
                # drive depth negative so the real depth-0 `,` was missed and the
                # brace misclassified as a block. Closures are decided BEFORE this
                # scan (named-param / capture-list checks above), so dropping
                # `<`/`>` here cannot regress closure parsing. Only `()`/`[]`/`{}`
                # — which cannot be a comparison — bound nested `,`/`:`.
                if t.type in (TokenType.LPAREN, TokenType.LBRACE,
                              TokenType.LBRACKET):
                    depth += 1
                elif t.type in (TokenType.RPAREN, TokenType.RBRACE,
                                TokenType.RBRACKET):
                    depth -= 1
                self.advance()
        finally:
            self.pos = saved

    def _parse_map_literal(self) -> MapLiteral:
        """Parse `{k1: v1, k2: v2, ...}` or the empty map `{:}` (design 54)."""
        start = self.current()
        self.expect(TokenType.LBRACE)
        self.skip_newlines()
        # Empty map `{:}`.
        if self.match(TokenType.COLON):
            self.advance()
            self.skip_newlines()
            self.expect(TokenType.RBRACE, "Expected '}' after '{:' (empty map)")
            return MapLiteral(entries=[], line=start.line, column=start.column)
        entries = []
        while not self.match(TokenType.RBRACE):
            key = self.parse_expression()
            self.expect(TokenType.COLON, "Expected ':' between map key and value")
            value = self.parse_expression()
            entries.append((key, value))
            self.skip_newlines()
            if self.match(TokenType.COMMA):
                self.advance()
                self.skip_newlines()
            else:
                break
        self.skip_newlines()
        self.expect(TokenType.RBRACE, "Expected '}' at end of map literal")
        return MapLiteral(entries=entries, line=start.line, column=start.column)

    def _parse_set_literal(self) -> SetLiteral:
        """Parse `{a, b, ...}` (design 54, two or more elements)."""
        start = self.current()
        self.expect(TokenType.LBRACE)
        self.skip_newlines()
        elements = []
        while not self.match(TokenType.RBRACE):
            elements.append(self.parse_expression())
            self.skip_newlines()
            if self.match(TokenType.COMMA):
                self.advance()
                self.skip_newlines()
            else:
                break
        self.skip_newlines()
        self.expect(TokenType.RBRACE, "Expected '}' at end of set literal")
        return SetLiteral(elements=elements, line=start.line, column=start.column)

    # === Closure Parsing ===

    def _parse_closure_expression(self) -> ClosureExpr:
        """Parse a closure expression: { x in x * 2 } or { $0 * 2 }

        An optional bracketed capture list may precede the parameters (design
        16/29): `{ [&var sum] x in ... }`, `{ [move conn] in ... }`. A `[...]`
        immediately after `{` is a capture list ONLY when it is followed (after
        optional params) by `in`; otherwise it is an array-literal body
        (`{ [1, 2, 3] }`).
        """
        start = self.current()
        self.advance()  # consume '{'
        self.skip_newlines()

        # Optional bracketed capture list.
        capture_specs = []
        if self.match(TokenType.LBRACKET) and self._closure_capture_list_ahead():
            capture_specs = self._parse_capture_list()
            self.skip_newlines()

        # Check for named params: { x in ... } or { x, y in ... } or { x: Type in ... }
        params = []
        if self._is_closure_with_named_params():
            params = self._parse_closure_params()
            self.expect(TokenType.IN, "Expected 'in' after closure parameters")
            self.skip_newlines()
        elif capture_specs and self.match(TokenType.IN):
            # `{ [caps] in ... }` — capture list, no params.
            self.advance()
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
            capture_specs=capture_specs,
            line=start.line,
            column=start.column
        )

    def _closure_capture_list_ahead(self) -> bool:
        """Disambiguate a bracketed capture list from an array-literal body.

        Current token is `[`. It begins a capture list iff, after the matching
        `]` and any closure params, an `in` follows at depth 0 (Swift's rule).
        `{ [x] in ... }` is a capture list; `{ [1, 2, 3] }` is an array body.
        """
        saved = self.pos
        try:
            # Skip the bracketed group to its matching `]`.
            depth = 0
            while True:
                t = self.current()
                if t.type == TokenType.EOF:
                    return False
                if t.type == TokenType.LBRACKET:
                    depth += 1
                elif t.type == TokenType.RBRACKET:
                    depth -= 1
                    self.advance()
                    if depth == 0:
                        break
                    continue
                self.advance()
            # After `]`: scan for `in` at depth 0 before a `}` or a statement.
            depth = 0
            while True:
                t = self.current()
                if t.type == TokenType.EOF:
                    return False
                if depth == 0 and t.type == TokenType.RBRACE:
                    return False
                if depth == 0 and t.type == TokenType.IN:
                    return True
                if t.type in (TokenType.LT, TokenType.LPAREN, TokenType.LBRACE,
                              TokenType.LBRACKET):
                    depth += 1
                elif t.type in (TokenType.GT, TokenType.RPAREN, TokenType.RBRACE,
                                TokenType.RBRACKET):
                    depth -= 1
                if depth == 0 and t.type in (
                    TokenType.PLUS, TokenType.MINUS, TokenType.STAR, TokenType.SLASH,
                    TokenType.EQ, TokenType.NEQ, TokenType.RETURN, TokenType.IF,
                    TokenType.WHILE, TokenType.ASSIGN, TokenType.SEMICOLON,
                    TokenType.LET,
                ):
                    return False
                self.advance()
        finally:
            self.pos = saved

    def _parse_capture_list(self) -> List['CaptureSpec']:
        """Parse `[ &var sum, move conn, copy v, x ]` (design 16/29)."""
        from ast_nodes import CaptureSpec
        self.expect(TokenType.LBRACKET)
        self.skip_newlines()
        specs = []
        while not self.match(TokenType.RBRACKET):
            tok = self.current()
            mode = 'plain'
            if self.match(TokenType.AMPERSAND):
                self.advance()
                if self.match(TokenType.VAR):
                    self.advance()
                    mode = 'ref_var'
                else:
                    mode = 'ref'
            elif self.match(TokenType.MOVE):
                self.advance()
                mode = 'move'
            elif self.match_ident('copy'):
                self.advance()
                mode = 'copy'
            name_tok = self.expect(TokenType.IDENT, "Expected capture name")
            specs.append(CaptureSpec(name=name_tok.value, mode=mode,
                                     line=tok.line, column=tok.column))
            if self.match(TokenType.COMMA):
                self.advance()
                self.skip_newlines()
            else:
                break
        self.skip_newlines()
        self.expect(TokenType.RBRACKET, "Expected ']' after capture list")
        return specs

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

                # Source position of this `{` so the sub-parsed expression's
                # diagnostics point at the real call site (design 99). Lines
                # are exact; columns approximate under escape sequences (each
                # source escape like `\n` is one raw char), which is fine —
                # the line is what diagnostics need.
                prefix = raw_value[:i]
                newlines = prefix.count('\n')
                if newlines:
                    brace_line = line + newlines
                    brace_column = i - prefix.rfind('\n')
                else:
                    brace_line = line
                    brace_column = column + 1 + i  # +1 for the opening quote

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

                # An EMPTY brace pair is a format placeholder (design 137), not
                # an expression to parse: `panic("out of {}", what)` fills it
                # from the argument list. Sub-parsing "" used to be the error
                # "Invalid expression in string interpolation".
                expr_str = ''.join(expr_chars)
                if expr_str.strip() == "":
                    expressions.append(FormatPlaceholder(
                        line=brace_line, column=brace_column))
                    continue

                # Parse the expression using a sub-lexer and sub-parser
                expr = self._parse_expression_from_string(expr_str, brace_line, brace_column)
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
            # Create a sub-parser with these tokens. Thread the enclosing file
            # through so a `#file`/`#function` (design 98) inside an
            # interpolation resolves against the real source, not "".
            sub_parser = Parser(sub_tokens, source_file=self.source_file)
            expr = sub_parser.parse_expression()
            # The sub-lexer numbered everything from 1:1; rebase onto the
            # enclosing string's source position so diagnostics inside an
            # interpolation point at the real line (design 99).
            self._rebase_interpolation_positions(expr, line, column)
            return expr
        except SyntaxError as e:
            preview = expr_str[:30] + "..." if len(expr_str) > 30 else expr_str
            raise SyntaxError(
                f"Invalid expression in string interpolation at {line}:{column}\n"
                f"  Expression: {{{preview}}}\n"
                f"  Error: {e}\n"
                f"  Hint: Use \\{{ and \\}} for literal braces in interpolated strings"
            )

    def _rebase_interpolation_positions(self, node, base_line: int, base_column: int, _seen=None) -> None:
        """Shift a sub-parsed interpolation expression tree from sub-lexer
        coordinates (1-based within the `{...}` text) to source coordinates.

        A node on sub-line 1 sits on the string's line, columns offset past the
        `{`; deeper sub-lines (rare: an interpolation spanning lines) keep
        their column and offset the line. Unset positions (0) are stamped with
        the brace position so no node is left reporting 1:1 (design 99)."""
        # `_seen` is a within-one-walk cycle guard over physical nodes (the
        # rebase walks arbitrary `vars(node)` graphs, which can alias), not the
        # persistent identity design 126 R2 replaced.
        if _seen is None:
            _seen = set()
        if node is None or id(node) in _seen:
            return
        _seen.add(id(node))
        if isinstance(node, (list, tuple)):
            for item in node:
                self._rebase_interpolation_positions(item, base_line, base_column, _seen)
            return
        if not hasattr(node, '__dict__'):
            return
        sub_line = getattr(node, 'line', None)
        if isinstance(sub_line, int):
            sub_column = getattr(node, 'column', 0) or 0
            if sub_line <= 1:
                node.line = base_line
                node.column = base_column + sub_column  # `{` at base_column; expr starts after it
            else:
                node.line = base_line + (sub_line - 1)
        for value in vars(node).values():
            if isinstance(value, (list, tuple)) or hasattr(value, '__dict__'):
                self._rebase_interpolation_positions(value, base_line, base_column, _seen)

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
            elif isinstance(expr, StringInterpolation):
                # `$N` inside an interpolation (`{ "v={$0}" }`) counts toward the
                # closure's arity — a natural spelling for a `(T) -> String`
                # shorthand closure (brief 36's map Int->String test).
                for sub in expr.expressions:
                    visit_expr(sub)
            elif isinstance(expr, ForceUnwrap):
                visit_expr(expr.expr)
            elif isinstance(expr, NilCoalesce):
                visit_expr(expr.expr)
                visit_expr(expr.default)
            elif isinstance(expr, OptionalChain):
                visit_expr(expr.expr)
            elif isinstance(expr, (BindOptional, OptionalEvalExpr)):
                visit_expr(expr.expr)
            elif isinstance(expr, OptionalChainAssign):
                visit_expr(expr.target)
                visit_expr(expr.value)
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
                    visit_expr(stmt.target)
                    visit_expr(stmt.value)
                elif isinstance(stmt, CompoundAssignStatement):
                    visit_expr(stmt.target)
                    visit_expr(stmt.value)
                elif isinstance(stmt, ReturnStatement):
                    visit_expr(stmt.value)
            if block.final_expr:
                visit_expr(block.final_expr)

        visit_block(body)
        return max_index + 1 if max_index >= 0 else 0

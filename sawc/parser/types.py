"""
Type parsing methods for the Saw parser.

This module provides mixin methods for parsing type annotations including
primitive types, optional types, array types, tuple types, function types,
pointer types, and generic type arguments.

Usage:
    class Parser(TypeParsingMixin, ...):
        pass
"""

from typing import List
from lexer import TokenType
from ast_nodes import SawType, TypeKind


class CommittedGenericError(SyntaxError):
    """A generic-list error the parser must REPORT rather than backtrack from.

    The speculative "is this `<` a generic argument list or a comparison?"
    lookahead in `parser/expressions.py` restores its position on any
    `SyntaxError` and re-reads the `<` as an operator. That is right for a `<`
    that was never a generic, and wrong for a list that IS one and is merely
    ill-formed — backtracking there swallows the real diagnostic and reports
    something unrecognizable from the comparison reading instead. Errors under
    this base are let through by every speculative site.
    """


class GenericListTrailingComma(CommittedGenericError):
    """A `,` sitting directly before `>` in a generic list (design 129).

    Trailing commas are allowed in the `()`/`[]` lists that the wrapping rule
    exists to serve, and rejected in `<...>`, which has no wrapping idiom to
    serve.
    """


class ReferenceTypeArgument(CommittedGenericError):
    """A generic argument that NAMES a reference — `Vector<&Int>`, `f<&Int>(x)`
    (DF-163d).

    References are parameters only, and a type argument is the one position that
    smuggles one past every declaration-side rule: `Vector<&Int>` never writes a
    `&` in a field or a return type, yet `v.push(&x)` is a genuine call argument
    and the container outlives the call. So the refusal is at the ARGUMENT, not
    at the call.
    """


class TypeParsingMixin:
    """Mixin providing type parsing methods for Parser."""

    def parse_return_clause(self, what: str) -> SawType:
        """Parse an optional `-> T` return clause, defaulting to `Void`.

        Every declaration that has a signature funnels its return type through
        here — `func`, extension method / `init`, trait requirement, `extern
        func` — so the parameters-only rule below is stated once and holds in
        every position. The function-TYPE grammar has its own arrow (it is not
        optional there) and calls `reject_reference_return` directly.
        """
        if not self.match(TokenType.ARROW):
            return SawType(TypeKind.VOID)
        self.advance()
        anchor = self.current()
        return_type = self.parse_type()
        self.reject_reference_return(return_type, anchor, what)
        return return_type

    def reject_reference_return(self, return_type: SawType, anchor,
                                what: str) -> None:
        """A return type may not name a reference (DF-163a).

        References in Saw are PARAMETERS ONLY: a `&T`/`&var T` borrows storage
        the caller owns for exactly the duration of the call, and the Law of
        Exclusivity is fully static only because of that — every live reference
        was created at some call expression still on the stack (LANGUAGE_SPEC
        "no-escape invariant", designs 88/106). A declared `-> &T` broke the
        invariant silently: `func dangle() -> &Int { let local = 99
        return &local }` compiled and printed 99 out of a dead frame.

        The reference is refused wherever the return type NAMES one, not only at
        the top level — a `(Int, &Int)` or a `&Int?` escapes the pointer exactly
        as well. The walk deliberately stops at a nested function TYPE: its
        parameters take references legitimately (`(&T) sync -> R` is the
        `with_ref` callback), and its own return was checked when it was parsed.
        """
        found = self._first_reference_in(return_type)
        if found is None:
            return
        value = found.inner_type if found.inner_type is not None else "T"
        lends = f"`... borrows -> {value}`"
        if found is return_type:
            names_it = "is a reference"
            fix = f"Return the value instead (`-> {value}`)"
        else:
            names_it = f"names a reference (`{found}`)"
            fix = (f"Return the value instead (drop the `&`: `{found}` becomes "
                   f"`{value}`)")
        self.error_at(
            anchor,
            f"{what} may not return a reference: the return type "
            f"`{return_type}` {names_it}, and references in Saw are PARAMETERS "
            f"ONLY — a reference borrows storage for the duration of one call "
            f"and may not escape it (designs 88/106; the Law of Exclusivity is "
            f"statically sound only because every live reference belongs to a "
            f"call still on the stack). Returning one hands back a pointer into "
            f"the frame that just died. {fix}, or — to hand out storage the "
            f"receiver already owns — declare a `borrows` accessor ({lends} "
            f"with `lend`, design 141), which lends the place for a window "
            f"rather than letting a pointer out")

    # The rule every parameters-only refusal states, in one place (DF-163a/d).
    PARAMETERS_ONLY = (
        "references in Saw are PARAMETERS ONLY — a reference borrows storage "
        "for the duration of one call and may not escape it (designs 88/106; "
        "the Law of Exclusivity is statically sound only because every live "
        "reference belongs to a call still on the stack)")

    @staticmethod
    def _lend_out(value) -> str:
        """The second way out: lend the storage instead of naming a pointer."""
        return (f"declare a `borrows` accessor (`... borrows -> {value}` with "
                f"`lend`, design 141), which lends the place for a window "
                f"rather than letting a pointer out")

    def reject_reference_field(self, field_name: str, struct_name: str,
                               field_type: SawType, anchor) -> None:
        """A struct FIELD may not name a reference (DF-163d).

        A field is storage that outlives every call, so a reference in one is
        the no-escape invariant broken by construction — and it is reachable
        without ever writing a `&` in a signature, since a struct literal
        (`Holder(r: &x)`) is not a call argument. Refusing the DECLARATION
        closes the construction with it: no field has a reference type, so no
        initializer can supply one.
        """
        found = self._first_reference_in(field_type)
        if found is None:
            return
        value = found.inner_type if found.inner_type is not None else "T"
        if found is field_type:
            names_it = "is a reference"
            fix = f"Store the value instead (`{field_name}: {value}`)"
        else:
            names_it = f"names a reference (`{found}`)"
            fix = (f"Store the value instead (drop the `&`: `{found}` becomes "
                   f"`{value}`)")
        self.error_at(
            anchor,
            f"field `{field_name}` of `{struct_name}` may not be a reference: "
            f"its type `{field_type}` {names_it}, and {self.PARAMETERS_ONLY}. "
            f"A field outlives every call that could have created the "
            f"reference, so the pointer it holds outlives the storage it "
            f"names. {fix}, or — to hand out storage this type already owns — "
            f"{self._lend_out(value)}")

    def reject_reference_type_arg(self, arg: SawType, anchor) -> None:
        """A generic ARGUMENT may not name a reference (DF-163d).

        `Vector<&Int>` writes no `&` in any field or return type, yet
        `v.push(&x)` fills it through a genuine call argument and the container
        outlives that call — so the refusal belongs at the type argument, not at
        the call. Covers both spellings a type argument has: a type position
        (`let v: Vector<&Int>`) and an instantiation (`idn<&Int>(&x)`).

        Raised rather than reported so the speculative generic-vs-comparison
        lookahead reports it instead of backtracking (see
        `CommittedGenericError`).
        """
        found = self._first_reference_in(arg)
        if found is None:
            return
        value = found.inner_type if found.inner_type is not None else "T"
        if found is arg:
            names_it = "is a reference"
        else:
            names_it = f"names a reference (`{found}`)"
        raise ReferenceTypeArgument(
            f"Parse error at {anchor.line}:{anchor.column}: a generic argument "
            f"may not be a reference: `{arg}` {names_it}, and "
            f"{self.PARAMETERS_ONLY}. A generic holds its argument as STORAGE "
            f"— `Vector<&Int>` fills through an ordinary call argument "
            f"(`v.push(&x)`) and then outlives that call — so the reference is "
            f"refused here rather than at the call. Use the value type instead "
            f"(`{value}`), or — to reach an element the container already owns "
            f"— {self._lend_out(value)}")

    def _first_reference_in(self, t: SawType):
        """The first reference type reachable from `t` without entering a
        function type, or None. Pre-order, so an outer `&T` names itself."""
        if t is None:
            return None
        if t.kind == TypeKind.REFERENCE:
            return t
        if t.kind == TypeKind.FUNCTION:
            return None
        parts = []
        if t.kind == TypeKind.OPTIONAL:
            parts.append(t.inner_type)
        if t.kind == TypeKind.ARRAY:
            parts.append(t.array_element_type)
        parts.extend(t.element_types or [])
        parts.extend(t.type_args or [])
        for p in parts:
            hit = self._first_reference_in(p)
            if hit is not None:
                return hit
        return None

    def parse_type(self, allow_nested_optional: bool = True) -> SawType:
        """Parse a type annotation, including optional suffixes.

        `?` NESTS (DF-174c): `Int??` is an optional of an optional, `String???`
        three deep, and the sugar reaches every position a type is written
        because every one of them funnels through here. `Optional<Int?>`
        remains the generic spelling and parses to the identical type — the
        typechecker resolves `Optional<T>` to `T?` (design 176 unit 9), so
        neither spelling is privileged.

        The lexer's maximal munch makes `Int??` come through as one
        DOUBLE_QUESTION token, so the loop below counts it as TWO layers rather
        than asking the lexer to stop fusing. That is deliberate: `??` stays one
        token for the nil-coalescing operator, both lexers keep byte-identical
        token streams, and the lexdiff parity harness needs no change at all.
        (The design-129 `<<` precedent splits in the other direction — the
        lexer leaves `<` `<` apart so `Vector<Box<Int>>` closes naturally, and
        the parser fuses them in expression position. Same principle, opposite
        default: fuse where the common reading is, split where the rarer one
        is.)

        `allow_nested_optional=False` is the ONE position where the type
        grammar and the expression grammar meet at a `??`: the target of an
        `as` cast is followed by an expression continuation, so `x as Int? ?? y`
        must read as a cast to `Int?` and then the coalescing operator. A cast
        to a nested optional is not a thing anyone writes — `as` converts
        numbers, projects aliases and takes addresses — so the operator wins
        there and the suffix loop stops at a `?`. Nested types INSIDE the cast
        target are unaffected (`x as Vector<Int??>` re-enters this function
        without the restriction).
        """
        # Parse base type
        base_type = self._parse_base_type()

        # Optional suffixes, innermost first: `Int??` is `Optional<Optional<Int>>`.
        while True:
            if self.match(TokenType.QUESTION):
                self.advance()
                base_type = SawType(TypeKind.OPTIONAL, inner_type=base_type)
            elif allow_nested_optional and self.match(TokenType.DOUBLE_QUESTION):
                self.advance()
                base_type = SawType(
                    TypeKind.OPTIONAL,
                    inner_type=SawType(TypeKind.OPTIONAL, inner_type=base_type))
            else:
                break

        return base_type

    # Mapping from type name strings to TypeKind for built-in types
    BUILTIN_TYPES = {
        'Int': TypeKind.INT,
        'Float': TypeKind.FLOAT,
        'Bool': TypeKind.BOOL,
        'String': TypeKind.STRING,
        'Void': TypeKind.VOID,  # explicit unit type, e.g. a `(T) -> Void` closure
        'Never': TypeKind.NEVER,  # bottom type; a `-> Never` fn diverges (design 49/58)
        'UInt': TypeKind.UINT,  # System-width unsigned integer
        # Fixed-width signed integers
        'Int8': TypeKind.INT8,
        'Int16': TypeKind.INT16,
        'Int32': TypeKind.INT32,
        'Int64': TypeKind.INT64,
        # Fixed-width unsigned integers
        'UInt8': TypeKind.UINT8,
        'UInt16': TypeKind.UINT16,
        'UInt32': TypeKind.UINT32,
        'UInt64': TypeKind.UINT64,
    }

    def _parse_base_type(self) -> SawType:
        """Parse a non-optional base type."""
        token = self.current()

        # Check for `sync` function type: sync (T, ...) -> R (design 22).
        # Check for reference type: &T or &var T
        if token.type == TokenType.AMPERSAND:
            self.advance()  # consume '&'

            # Check for &var T (mutable reference)
            is_mutable = False
            if self.match(TokenType.VAR):
                is_mutable = True
                self.advance()

            # Parse the inner type
            inner_type = self.parse_type()

            return SawType(TypeKind.REFERENCE, inner_type=inner_type, reference_mutable=is_mutable)

        if token.type == TokenType.LBRACKET:
            # Array type: [Type; Size]. The size is a constant EXPRESSION since
            # design 148 — a literal as before, but also a const generic
            # parameter (`[UInt8; N]`) or arithmetic over them. A literal is
            # resolved right here; anything else carries its expression until
            # there is an environment to evaluate it in.
            #
            # design 185 unit 2: the FULL expression grammar, the same one the
            # repeat count `[v; N]` takes. `]` closes this position, so none of
            # what forced design 148's narrow grammar applies here — that was
            # the generic-argument position, closed by `>`, where a general
            # parser would read `FixedBuf<N + 1>` as a comparison and eat the
            # delimiter. One rule spelled two ways had two failure modes: `<<`
            # and `dep.SIZE` (DF-172l) were PARSE errors in a type and clean
            # semantic ones in a repeat count. Now both positions parse
            # everything and `const_eval` gives the one answer.
            self.advance()  # consume '['
            element_type = self.parse_type()
            self.expect(TokenType.SEMICOLON, "Expected ';' in array type")
            size_expr = self.parse_expression()
            self.expect(TokenType.RBRACKET, "Expected ']' after array type")
            return self._array_type(element_type, size_expr)
        elif token.type == TokenType.LPAREN:
            # Could be tuple type: (Type, Type, ...) or function type: (Type, Type) -> ReturnType
            self.advance()
            element_types = []
            field_names = []  # per-element name or None (design 63 named tuples)

            def _parse_tuple_element():
                # `IDENT :` prefix marks a named field. `IDENT .` / `IDENT <` /
                # `IDENT IDENT` (a bare type name) are positional — only a colon
                # begins a label.
                if (self.current().type == TokenType.IDENT
                        and self.peek(1).type == TokenType.COLON):
                    fname = self.advance().value
                    self.advance()  # consume ':'
                    field_names.append(fname)
                else:
                    field_names.append(None)
                element_types.append(self.parse_type())

            if not self.match(TokenType.RPAREN):
                _parse_tuple_element()
                while self.match(TokenType.COMMA):
                    self.advance()
                    # Trailing comma (design 129).
                    if self.match(TokenType.RPAREN):
                        break
                    _parse_tuple_element()
            self.expect(TokenType.RPAREN)

            # Post-parameter effect slot (designs 18/22/16/29/130): `(T) sync -> U`
            # (checked suspension-free), `(T) escaping -> U` (escaping function
            # value) and `(T) unsafe -> U` (design 130 — a closure whose own body
            # names an unsafe type), composing in canonical order
            # `(T) unsafe sync escaping -> U`. `sync`/`escaping` are CONTEXTUAL
            # identifiers — after a parenthesized list only `->` (function type)
            # or a closing delimiter (tuple) may follow, so a run of them is
            # unambiguous only when terminated by `->`. Otherwise this is a tuple
            # and the identifiers are left unconsumed. `unsafe` is a keyword and
            # rides the same run so the three read as one slot. This is Swift's
            # `throws`/`async` position.
            # `borrows` (design 141) rides the same run, last in canonical
            # order `unsafe sync escaping borrows`. It is a reserved word like
            # `unsafe`, so it matches on token type.
            is_sync = False
            is_escaping = False
            is_unsafe = False
            is_borrows = False
            _RUN_TOKENS = {TokenType.UNSAFE: 'unsafe',
                           TokenType.BORROWS: 'borrows'}
            run = []
            k = 0
            while True:
                t = self.peek(k)
                if t.type in _RUN_TOKENS:
                    run.append(_RUN_TOKENS[t.type])
                elif t.type == TokenType.IDENT and t.value in ('sync', 'escaping'):
                    run.append(t.value)
                else:
                    break
                k += 1
            if run and self.peek(k).type == TokenType.ARROW:
                if 'borrows' in run:
                    # design 141 v1 fence: there are no borrows function
                    # VALUES. A borrows call yields a PLACE for a window, and a
                    # place is not a value — binding it, storing it in a field
                    # or erasing it behind `any Trait` would all outlive the
                    # window. The grammar accepts the run so the refusal can
                    # name the word instead of failing as a syntax error.
                    self.error(
                        "a function TYPE may not be `borrows` (design 141 v1): "
                        "a borrows call yields a place for a window, and a "
                        "place is never a value, so there is nothing to bind, "
                        "store or erase. Call the borrows method at the use "
                        "site instead")
                for kw in run:
                    if kw == 'sync':
                        is_sync = True
                    elif kw == 'unsafe':
                        is_unsafe = True
                    elif kw == 'borrows':
                        is_borrows = True
                    else:
                        is_escaping = True
                    self.advance()

            # Check for arrow to distinguish function type from tuple
            if self.match(TokenType.ARROW):
                self.advance()
                ret_anchor = self.current()
                return_type = self.parse_type()
                self.reject_reference_return(return_type, ret_anchor,
                                             "a function TYPE")
                fn_type = SawType(TypeKind.FUNCTION, param_types=element_types, func_return_type=return_type)
                if is_sync:
                    fn_type.func_is_sync = True
                if is_escaping:
                    fn_type.func_is_escaping = True
                if is_unsafe:
                    fn_type.func_is_unsafe = True
                if is_borrows:
                    fn_type.func_is_borrows = True
                return fn_type
            else:
                # All-or-nothing labeling (design 63): a partially-labeled tuple
                # type is an error.
                named = [n for n in field_names if n is not None]
                tfn = None
                if named:
                    if len(named) != len(field_names):
                        self.error("named tuple type must label every field "
                                   "(all-or-nothing)")
                    tfn = field_names
                return SawType(TypeKind.TUPLE, element_types=element_types,
                               tuple_field_names=tfn)
        elif token.type == TokenType.IDENT:
            # Could be a built-in type, struct, enum, type parameter, Self, pointer type,
            # or module-qualified type (lib.Point)
            self.advance()
            name = token.value

            # Contextual `any Trait` existential (design 51). `any` stays a valid
            # identifier: it names an erased type ONLY when immediately followed by
            # a trait name (two adjacent identifiers never form any other type), so
            # `any` alone (or `any.Foo`, `any<...>`) still falls through to the
            # normal named-type path below. The trait reference may be dotted
            # (`any lib.Shape`); associated-type pinning (`any Iterator<Item=Int>`)
            # is deferred, so no `<...>` is consumed here.
            if name == "any" and self.match(TokenType.IDENT):
                trait_tok = self.expect(TokenType.IDENT, "Expected trait name after 'any'")
                trait_name = trait_tok.value
                while self.match(TokenType.DOT):
                    self.advance()
                    part = self.expect(TokenType.IDENT, "Expected identifier after '.' in trait name")
                    trait_name = f"{trait_name}.{part.value}"
                return SawType(TypeKind.EXISTENTIAL, existential_trait=trait_name)

            # Check for built-in types (Int, String, Bool, etc.)
            if name in self.BUILTIN_TYPES:
                return SawType(self.BUILTIN_TYPES[name])

            # Special case for Self type (used in trait method return types)
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

            # Check for module-qualified types: lib.Point, std.io.Error
            while self.match(TokenType.DOT):
                self.advance()  # consume '.'
                next_token = self.expect(TokenType.IDENT, f"Expected identifier after '.' in type {name}")
                name = f"{name}.{next_token.value}"

            # Check for type arguments: Box<Int>, Pair<A, B>
            type_args = None
            if self.match(TokenType.LT):
                type_args = self._parse_type_args()

            # For now, parse as STRUCT - type checker will determine if it's
            # actually a type parameter or enum
            return SawType(TypeKind.STRUCT, struct_name=name, type_args=type_args)
        else:
            self.error(f"Expected type, got {token.type.name}")

    # ---------------------------------------------------------------- design 148
    # Constant expressions in a GENERIC ARGUMENT: `FixedBuf<2 * 128>`.
    # Deliberately its own small grammar rather than `parse_expression`, for one
    # reason that decides it: a generic argument list is closed by `>`, which is
    # also a comparison operator, so a general expression parser would read
    # `FixedBuf<N + 1>` as a comparison and eat the delimiter. Restricting the
    # grammar to what a constant can actually be — literals, names, `+ - * / %`,
    # parentheses, `sizeof`/`alignof` — makes `>` unambiguous by construction.
    #
    # design 185 unit 2 took the ARRAY LENGTH out of here: `[T; N]` is closed by
    # `]`, so it can and does take the full expression grammar. This one keeps
    # the narrow scope, and `<<`/`>>` are the reason it must — the shift tokens
    # ARE the delimiter. A generic argument that needs them names a `static` or
    # a const parameter folded from one.

    _CONST_ADD_OPS = None   # filled below (TokenType is imported at module load)
    _CONST_MUL_OPS = None

    def parse_const_expr(self, what: str = "constant"):
        """Parse a constant expression (design 148). `what` names the position
        for the error a malformed one raises."""
        return self._const_additive(what)

    def _const_additive(self, what: str):
        from ast_nodes import BinaryOp
        left = self._const_multiplicative(what)
        while self.match(TokenType.PLUS, TokenType.MINUS):
            op_tok = self.advance()
            right = self._const_multiplicative(what)
            left = BinaryOp(left=left, op=op_tok.value, right=right,
                            line=op_tok.line, column=op_tok.column)
        return left

    def _const_multiplicative(self, what: str):
        from ast_nodes import BinaryOp
        left = self._const_unary(what)
        while self.match(TokenType.STAR, TokenType.SLASH, TokenType.PERCENT):
            op_tok = self.advance()
            right = self._const_unary(what)
            left = BinaryOp(left=left, op=op_tok.value, right=right,
                            line=op_tok.line, column=op_tok.column)
        return left

    def _const_unary(self, what: str):
        from ast_nodes import UnaryOp
        if self.match(TokenType.MINUS):
            op_tok = self.advance()
            return UnaryOp(op='-', operand=self._const_unary(what),
                           line=op_tok.line, column=op_tok.column)
        return self._const_primary(what)

    def _const_primary(self, what: str):
        from ast_nodes import IntLiteral, Identifier, FunctionCall
        token = self.current()
        if token.type == TokenType.INT:
            self.advance()
            return IntLiteral(value=int(token.value), line=token.line,
                              column=token.column)
        if token.type == TokenType.LPAREN:
            self.advance()
            inner = self._const_additive(what)
            self.expect(TokenType.RPAREN, f"Expected ')' in {what}")
            return inner
        if token.type == TokenType.IDENT:
            self.advance()
            if token.value in ("sizeof", "alignof") and self.match(TokenType.LT):
                type_args = self._parse_type_args()
                self.expect(TokenType.LPAREN, f"Expected '(' after `{token.value}<T>`")
                self.expect(TokenType.RPAREN, f"Expected ')' after `{token.value}<T>(`")
                return FunctionCall(name=token.value, arguments=[],
                                    type_args=type_args, line=token.line,
                                    column=token.column)
            return Identifier(name=token.value, line=token.line,
                              column=token.column)
        self.error(f"Expected {what}, got {token.type.name}")

    @staticmethod
    def _is_const_expr_start(token) -> bool:
        """Whether a generic ARGUMENT starting here is a value, not a type.

        Only the shapes a type can never begin with commit on sight. A bare
        identifier stays a type as far as the parser is concerned — `Foo<N>` is
        ambiguous by design, and the typechecker decides it against the
        parameter it lands on, which is the only place that knows.
        """
        return token.type in (TokenType.INT, TokenType.MINUS)

    def _array_type(self, element_type: SawType, size_expr) -> SawType:
        """Build an ARRAY type from a parsed length expression."""
        from ast_nodes import IntLiteral
        if isinstance(size_expr, IntLiteral):
            return SawType(TypeKind.ARRAY, array_element_type=element_type,
                           array_size=int(size_expr.value),
                           array_size_expr=size_expr)
        return SawType(TypeKind.ARRAY, array_element_type=element_type,
                       array_size_expr=size_expr)

    def _parse_type_args(self) -> List[SawType]:
        """Parse type arguments: <Int, String, ...>

        Reached only where the parser has COMMITTED to the generic reading, so
        newlines inside the list are insignificant (design 129) — in type position
        always, and in expression position (`f<Int>(x)`) once the speculative
        lookahead in `parse_primary` has entered here. A `<` that turns out to be
        a comparison never gets this far with its list intact: the lookahead
        restores the position and the operator parses normally.

        An argument may be a VALUE since design 148 (`FixedBuf<256>`), which is
        what `_parse_one_type_arg` sorts out.
        """
        self.expect(TokenType.LT)
        self._generic_depth += 1
        try:
            type_args = [self._parse_one_type_arg()]

            # Parse additional type arguments
            while self.match(TokenType.COMMA):
                comma = self.advance()
                if self.match(TokenType.GT):
                    raise GenericListTrailingComma(
                        f"Parse error at {comma.line}:{comma.column}: a trailing "
                        f"comma is not allowed in a generic argument list "
                        f"(it is allowed in `(...)` and `[...]` lists)")
                type_args.append(self._parse_one_type_arg())

            self.expect(TokenType.GT, "Expected '>' after type arguments")
        finally:
            self._generic_depth -= 1
        return type_args

    def _parse_one_type_arg(self) -> SawType:
        """Parse one generic argument, which may be a type or a VALUE (design 148).

        Three cases, and the ordering is the whole trick:
        - It starts with something no type can start with (`256`, `-1`): a
          value, decided on sight.
        - It parses as a type and is then followed by an arithmetic operator
          (`N + 1`, `SIZE * 2`): the type reading was only a prefix of a
          constant expression, so restore and re-read it as one.
        - Otherwise it is a type — including a bare `N`, which is genuinely
          ambiguous here and stays a type until the typechecker matches it
          against the parameter it lands on. That is the only place with enough
          information to tell a type parameter from a const one.
        """
        if self._is_const_expr_start(self.current()):
            return self._const_value_type(
                self.parse_const_expr("generic argument"))

        saved = self.pos
        try:
            t = self.parse_type()
        except CommittedGenericError:
            # A NESTED generic list already committed and failed (`Vector<Box<
            # &Int>>`) — its diagnostic is the real one, so it must not be
            # swallowed by the const-expression retry below.
            raise
        except SyntaxError:
            self.pos = saved
            return self._const_value_type(
                self.parse_const_expr("generic argument"))

        if self.match(TokenType.PLUS, TokenType.MINUS, TokenType.STAR,
                      TokenType.SLASH, TokenType.PERCENT):
            self.pos = saved
            return self._const_value_type(
                self.parse_const_expr("generic argument"))
        self.reject_reference_type_arg(t, self.tokens[saved])
        return t

    @staticmethod
    def _const_value_type(expr) -> SawType:
        """Wrap a parsed constant expression as a CONST_VALUE argument."""
        from ast_nodes import IntLiteral
        if isinstance(expr, IntLiteral):
            return SawType(TypeKind.CONST_VALUE, const_value=int(expr.value),
                           array_size_expr=expr)
        return SawType(TypeKind.CONST_VALUE, array_size_expr=expr)

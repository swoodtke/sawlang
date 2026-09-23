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
from noescape import first_reference_in


class CommittedGenericError(SyntaxError):
    """A generic-list error the parser must report rather than backtrack from.

    The speculative "generic argument list or comparison?" lookahead in
    `parser/expressions.py` restores its position on any `SyntaxError` and
    re-reads the `<` as an operator. For a list that is generic but
    ill-formed, that would swallow the real diagnostic. Every speculative site
    lets errors under this base through.
    """


class GenericListTrailingComma(CommittedGenericError):
    """A `,` directly before `>` in a generic list (design 129).

    Trailing commas are allowed in `()`/`[]` lists, which wrap across lines,
    and rejected in `<...>`, which has no wrapping idiom.
    """


class ReferenceTypeArgument(CommittedGenericError):
    """A generic argument that names a reference: `Vector<&Int>`, `f<&Int>(x)`.

    References are parameters only. `Vector<&Int>` writes no `&` in a field or
    return type, yet `v.push(&x)` is a genuine call argument and the container
    outlives the call, so the refusal is at the argument, not at the call.
    """


class TypeParsingMixin:
    """Mixin providing type parsing methods for Parser."""

    def parse_return_clause(self, what: str, lends: bool = False) -> SawType:
        """Parse an optional `-> T` return clause, defaulting to `Void`.

        ENTRY POINTS: every declaration with a signature (`func`, extension
        method / `init`, trait requirement, `extern func`), so the
        parameters-only rule holds in every position. The function-type grammar
        has a mandatory arrow and calls `reject_reference_return` directly.

        `lends=True` is the one exception, the `borrows` signature: it lends a
        place for a window rather than returning a reference, and
        `borrows -> &T` / `borrows -> &var T` say which window modes it opens.
        The reference is legal only at the top level of the clause;
        `borrows -> (Int, &Int)` still escapes a pointer and is refused.
        """
        if not self.match(TokenType.ARROW):
            return SawType(TypeKind.VOID)
        self.advance()
        anchor = self.current()
        return_type = self.parse_type()
        if lends and return_type.kind == TypeKind.REFERENCE:
            # The lent type itself is walked for nested references — `borrows ->
            # &(Int, &Int)` is refused on the inner one.
            self.reject_reference_return(return_type.inner_type, anchor, what)
            return return_type
        self.reject_reference_return(return_type, anchor, what)
        return return_type

    def reject_reference_return(self, return_type: SawType, anchor,
                                what: str) -> None:
        """A return type may not name a reference.

        References are parameters only: a `&T`/`&var T` borrows caller-owned
        storage for exactly the duration of the call, and the Law of
        Exclusivity is static only because every live reference was created at
        a call still on the stack (LANGUAGE_SPEC "no-escape invariant").

        The reference is refused wherever the return type names one, not only
        at the top level: `(Int, &Int)` or `&Int?` escapes the pointer as well.
        The walk stops at a nested function type, whose parameters take
        references legitimately and whose return was checked when parsed.
        """
        found = self._first_reference_in(return_type)
        if found is None:
            return
        value = found.inner_type if found.inner_type is not None else "T"
        lends = f"`... borrows -> &var {value}`"
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

    # The rule every parameters-only refusal states, in one place.
    PARAMETERS_ONLY = (
        "references in Saw are PARAMETERS ONLY — a reference borrows storage "
        "for the duration of one call and may not escape it (designs 88/106; "
        "the Law of Exclusivity is statically sound only because every live "
        "reference belongs to a call still on the stack)")

    @staticmethod
    def _lend_out(value) -> str:
        """The second way out: lend the storage instead of naming a pointer."""
        return (f"declare a `borrows` accessor (`... borrows -> &var {value}` "
                f"with `lend`, design 141), which lends the place for a window "
                f"rather than letting a pointer out")

    def reject_reference_field(self, field_name: str, struct_name: str,
                               field_type: SawType, anchor,
                               borrowing_struct: bool = False) -> None:
        """A struct field may not name a reference.

        A field is storage that outlives every call, so a reference in one
        breaks the no-escape invariant by construction. Refusing the
        declaration closes the struct-literal route (`Holder(r: &x)` is not a
        call argument) too.

        `borrowing_struct=True` is the one exception (design 275): a
        `borrows struct` value lives only inside one window, which charges the
        referent's root for its whole extent. The exception is top-level and
        shared only:
          * a nested reference (`pair: (Int, &T)`, `slot: &T?`) is refused,
            because the window tracks a field's root, not one buried inside;
          * a `&var T` field is refused, because it could reallocate storage
            another shared reader is walking, which the root alone would not
            catch.
        """
        if borrowing_struct and field_type.kind == TypeKind.REFERENCE:
            if field_type.reference_mutable:
                value = (field_type.inner_type if field_type.inner_type
                         is not None else "T")
                self.error_at(
                    anchor,
                    f"field `{field_name}` of `borrows struct {struct_name}` "
                    f"may not be an EXCLUSIVE reference: its type "
                    f"`{field_type}` is `&var`, and a borrowing struct holds "
                    f"SHARED references only. A window is shared, and an "
                    f"exclusive field would let this type reallocate the very "
                    f"storage another reader is walking through its own field "
                    f"— which recording the root alone would not catch. Lend "
                    f"it shared (`{field_name}: &{value}`); mutating this "
                    f"type's OWN state stays ordinary `&var self` on its "
                    f"methods")
            # The lent type itself is still walked: `&(Int, &T)` is refused on
            # the inner one.
            self.reject_reference_field(field_name, struct_name,
                                        field_type.inner_type, anchor)
            return
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
            f"{self._lend_out(value)}" + (
                f". To hold a lent place for the extent of ONE window, declare "
                f"the type `borrows struct {struct_name}` (design 275 U3): a "
                f"borrowing struct's values live only inside their window, "
                f"which is what makes the shared field sound"
                if found is field_type and not field_type.reference_mutable
                else ""))

    def reject_reference_payload(self, payload_name: str, variant_name: str,
                                 enum_name: str, payload_type: SawType,
                                 anchor) -> None:
        """An enum case payload may not name a reference.

        A payload is storage on exactly a struct field's terms: it lives in the
        enum value, which outlives every call that could have created the
        reference. Without this, a one-case enum would bypass the field rule.
        """
        found = self._first_reference_in(payload_type)
        if found is None:
            return
        value = found.inner_type if found.inner_type is not None else "T"
        if found is payload_type:
            names_it = "is a reference"
            fix = f"Store the value instead (`{payload_name}: {value}`)"
        else:
            names_it = f"names a reference (`{found}`)"
            fix = (f"Store the value instead (drop the `&`: `{found}` becomes "
                   f"`{value}`)")
        self.error_at(
            anchor,
            f"payload `{payload_name}` of case `{variant_name}` in enum "
            f"`{enum_name}` may not be a reference: its type `{payload_type}` "
            f"{names_it}, and {self.PARAMETERS_ONLY}. An enum value is storage "
            f"that outlives every call that could have created the reference, "
            f"so the pointer it holds outlives what it names. {fix}, or — to "
            f"hand out storage this type already owns — {self._lend_out(value)}")

    def reject_reference_type_arg(self, arg: SawType, anchor) -> None:
        """A generic argument may not name a reference.

        See `ReferenceTypeArgument` for why the refusal is at the argument.
        Covers both spellings: a type position (`let v: Vector<&Int>`) and an
        instantiation (`idn<&Int>(&x)`).

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
        """The first reference type reachable from `t`, as written.

        The parser's entry to the one no-escape walk (`noescape.py`). No
        resolver: an alias is just a name here; the typechecker resolves
        aliases in its pass over the same positions.
        """
        return first_reference_in(t)

    def parse_type(self, allow_nested_optional: bool = True) -> SawType:
        """Parse a type annotation, including optional suffixes.

        `?` nests: `Int??` is an optional of an optional, and every type
        position funnels through here. `Optional<Int?>` parses to the identical
        type.

        The lexer's maximal munch makes `Int??` one DOUBLE_QUESTION token, so
        the loop counts it as two layers; `??` stays one token for the
        nil-coalescing operator and both lexers stay in parity.

        `allow_nested_optional=False` is for an `as` cast target, the one place
        the type and expression grammars meet at `??`: `x as Int? ?? y` is a
        cast to `Int?` then coalescing. Types nested inside the target
        (`x as Vector<Int??>`) are unaffected.
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
        'Never': TypeKind.NEVER,  # bottom type; a `-> Never` fn diverges
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
            # Array type: [Type; Size]. The size is a constant expression: a
            # literal, a const generic parameter (`[UInt8; N]`) or arithmetic
            # over them. A literal is resolved here; anything else keeps its
            # expression until there is an environment to evaluate it in.
            #
            # It takes the full expression grammar, as the repeat count
            # `[v; N]` does, because `]` closes it unambiguously; `const_eval`
            # gives both positions the one answer.
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
            field_names = []  # per-element name or None (named tuples)

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
                    # Trailing comma.
                    if self.match(TokenType.RPAREN):
                        break
                    _parse_tuple_element()
            self.expect(TokenType.RPAREN)

            # Post-parameter effect slot: `(T) unsafe sync escaping borrows -> U`.
            # `sync`/`escaping`/`consumes` are contextual identifiers: after a
            # parenthesized list only `->` (function type) or a closing
            # delimiter (tuple) may follow, so a run of them counts only when
            # terminated by `->`; otherwise this is a tuple and they are left
            # unconsumed. `unsafe` and `borrows` are reserved words and match
            # on token type.
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
                elif t.type == TokenType.IDENT and t.value in ('sync', 'escaping',
                                                               'consumes'):
                    run.append(t.value)
                else:
                    break
                k += 1
            if run and self.peek(k).type == TokenType.ARROW:
                if 'consumes' in run:
                    # `consumes` describes a receiver, and a function type has
                    # none. The run is accepted so the refusal can name the
                    # word instead of failing as a syntax error (design 260).
                    self.error(
                        "a function TYPE may not be `consumes` (design 260 "
                        "v1): `consumes` describes what happens to a method's "
                        "RECEIVER, and a function type has no receiver. "
                        "Methods are not first-class values — call the "
                        "consuming method at the use site instead")
                if 'borrows' in run:
                    # No borrows function values: a borrows call yields a place
                    # for a window, and binding, storing or erasing it would
                    # outlive the window. The run is accepted so the refusal
                    # can name the word (design 141).
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
                # All-or-nothing labeling: a partially-labeled tuple type is an
                # error.
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

            # Contextual `any Trait` existential. `any` names an erased type only
            # when immediately followed by a trait name (two adjacent
            # identifiers never form any other type); `any` alone, `any.Foo` or
            # `any<...>` take the named-type path below. The trait may be dotted
            # (`any lib.Shape`); associated-type pinning is not supported, so no
            # `<...>` is consumed here.
            if name == "any" and self.match(TokenType.IDENT):
                trait_tok = self.expect(TokenType.IDENT, "Expected trait name after 'any'")
                trait_name = trait_tok.value
                while self.match(TokenType.DOT):
                    self.advance()
                    part = self.expect(TokenType.IDENT, "Expected identifier after '.' in trait name")
                    trait_name = f"{trait_name}.{part.value}"
                return SawType(TypeKind.EXISTENTIAL, existential_trait=trait_name,
                               written_name=trait_name,
                               written_file=self.source_file,
                               written_line=trait_tok.line,
                               written_column=trait_tok.column)

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
            # actually a type parameter or enum.
            #
            # `written_name` records the spelling: the typechecker rewrites
            # `struct_name` to the module-qualified identity in place, and the
            # prelude gate needs what the author typed (a bare `Data` must be
            # imported; `data.Data` already reached it through an import).
            return SawType(TypeKind.STRUCT, struct_name=name, type_args=type_args,
                           written_name=name, written_file=self.source_file,
                           written_line=token.line, written_column=token.column)
        else:
            self.error(f"Expected type, got {token.type.name}")

    # ---------------------------------------------------------------- design 148
    # Constant expressions in a generic argument: `FixedBuf<2 * 128>`.
    # Its own small grammar rather than `parse_expression`, because the list is
    # closed by `>`, which a general parser would read as a comparison
    # (`FixedBuf<N + 1>`). Restricting it to literals, names, `+ - * / %`,
    # parentheses and `sizeof`/`alignof` makes `>` unambiguous. Shifts are
    # excluded because `<<`/`>>` are the delimiters; a generic argument that
    # needs one names a `static` or a const parameter instead.

    _CONST_ADD_OPS = None   # filled below (TokenType is imported at module load)
    _CONST_MUL_OPS = None

    def parse_const_expr(self, what: str = "constant"):
        """Parse a constant expression. `what` names the position
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
            # Through the shared decoder, never `int()`: an INT token keeps its
            # canonical text, prefix included (`0x10`).
            return IntLiteral(value=self._decode_int_literal(token.value),
                              line=token.line, column=token.column)
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

        Only shapes a type can never begin with commit on sight. A bare
        identifier stays a type here: `Foo<N>` is ambiguous, and the
        typechecker decides it against the parameter it lands on. `sizeof` and
        `alignof` pass the same test, since they are built-in names that can
        never begin a type.
        """
        if token.type == TokenType.IDENT:
            return token.value in ("sizeof", "alignof")
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

        Reached only where the parser has committed to the generic reading, so
        newlines inside the list are insignificant: always in type position,
        and in expression position (`f<Int>(x)`) once the speculative lookahead
        in `parse_primary` enters here. A `<` that is a comparison never gets
        this far; the lookahead restores the position.

        An argument may be a value (`FixedBuf<256>`); `_parse_one_type_arg`
        sorts that out.
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
        """Parse one generic argument, which may be a type or a value.

        Three cases, in this order:
        - It starts with something no type can start with (`256`, `-1`): a
          value, decided on sight.
        - It parses as a type and is then followed by an arithmetic operator
          (`N + 1`, `SIZE * 2`): the type reading was only a prefix of a
          constant expression, so restore and re-read it as one.
        - Otherwise it is a type, including a bare `N`, which stays a type until
          the typechecker matches it against the parameter it lands on.
        """
        if self._is_const_expr_start(self.current()):
            return self._const_value_type(
                self.parse_const_expr("generic argument"))

        saved = self.pos
        try:
            t = self.parse_type()
        except CommittedGenericError:
            # A nested generic list already committed and failed (`Vector<Box<
            # &Int>>`); its diagnostic is the real one, so the const-expression
            # retry below must not swallow it.
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

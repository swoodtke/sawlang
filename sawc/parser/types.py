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


class GenericListTrailingComma(SyntaxError):
    """A `,` sitting directly before `>` in a generic list (design 129).

    Trailing commas are allowed in the `()`/`[]` lists that the wrapping rule
    exists to serve, and rejected in `<...>`, which has no wrapping idiom to
    serve. It is its own exception type so the speculative "is this `<` a generic
    or a comparison?" backtracking in `parser/expressions.py` can let it through
    instead of swallowing it and reporting something unrecognizable later.
    """


class TypeParsingMixin:
    """Mixin providing type parsing methods for Parser."""

    def parse_type(self) -> SawType:
        """Parse a type annotation, including optional suffix."""
        # Parse base type
        base_type = self._parse_base_type()

        # Check for optional suffix (?)
        if self.match(TokenType.QUESTION):
            self.advance()
            return SawType(TypeKind.OPTIONAL, inner_type=base_type)

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
            is_sync = False
            is_escaping = False
            is_unsafe = False
            run = []
            k = 0
            while ((self.peek(k).type == TokenType.IDENT
                    and self.peek(k).value in ('sync', 'escaping'))
                   or self.peek(k).type == TokenType.UNSAFE):
                run.append('unsafe' if self.peek(k).type == TokenType.UNSAFE
                           else self.peek(k).value)
                k += 1
            if run and self.peek(k).type == TokenType.ARROW:
                for kw in run:
                    if kw == 'sync':
                        is_sync = True
                    elif kw == 'unsafe':
                        is_unsafe = True
                    else:
                        is_escaping = True
                    self.advance()

            # Check for arrow to distinguish function type from tuple
            if self.match(TokenType.ARROW):
                self.advance()
                return_type = self.parse_type()
                fn_type = SawType(TypeKind.FUNCTION, param_types=element_types, func_return_type=return_type)
                if is_sync:
                    fn_type.func_is_sync = True
                if is_escaping:
                    fn_type.func_is_escaping = True
                if is_unsafe:
                    fn_type.func_is_unsafe = True
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

    def _parse_type_args(self) -> List[SawType]:
        """Parse type arguments: <Int, String, ...>

        Reached only where the parser has COMMITTED to the generic reading, so
        newlines inside the list are insignificant (design 129) — in type position
        always, and in expression position (`f<Int>(x)`) once the speculative
        lookahead in `parse_primary` has entered here. A `<` that turns out to be
        a comparison never gets this far with its list intact: the lookahead
        restores the position and the operator parses normally.
        """
        self.expect(TokenType.LT)
        self._generic_depth += 1
        try:
            type_args = [self.parse_type()]

            # Parse additional type arguments
            while self.match(TokenType.COMMA):
                comma = self.advance()
                if self.match(TokenType.GT):
                    raise GenericListTrailingComma(
                        f"Parse error at {comma.line}:{comma.column}: a trailing "
                        f"comma is not allowed in a generic argument list "
                        f"(it is allowed in `(...)` and `[...]` lists)")
                type_args.append(self.parse_type())

            self.expect(TokenType.GT, "Expected '>' after type arguments")
        finally:
            self._generic_depth -= 1
        return type_args

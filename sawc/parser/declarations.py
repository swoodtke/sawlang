"""
Declaration parsing methods for the Saw parser.

This module provides mixin methods for parsing top-level declarations including
functions, structs, enums, traits, extensions, extern blocks, and methods.

Usage:
    class Parser(DeclarationsMixin, ...):
        pass
"""

from typing import List, Optional, Tuple, Union
from lexer import TokenType
from ast_nodes import (
    Function, Parameter, Struct, StructField,
    Enum, EnumVariant,
    Trait, TraitMethod, AssociatedType,
    Extension, Method, TypeAssignment, TypeDefinition,
    ExternBlock, ExternFunction, StaticDecl,
    SawType, TypeKind, Visibility, TypeParameter,
    Attribute, KNOWN_ATTRIBUTES,
)


class DeclarationsMixin:
    """Mixin providing declaration parsing methods for Parser."""

    def _parse_qualified_name(self, error_msg: str) -> str:
        """Parse a potentially module-qualified name like 'Trait' or 'module.Trait'."""
        token = self.expect(TokenType.IDENT, error_msg)
        name = token.value
        # Check for module qualification (e.g., lib.Describable)
        while self.match(TokenType.DOT):
            self.advance()
            next_token = self.expect(TokenType.IDENT, f"Expected identifier after '.' in {name}")
            name = f"{name}.{next_token.value}"
        return name

    def parse_attributes(self) -> List[Attribute]:
        """Parse zero or more attribute lines: `@name`, `@name("string")` or
        `@name(<const expr>)`, each immediately preceding a declaration.

        The attribute grammar funnel: every `@` the language accepts is read
        here, so a new attribute is a `KNOWN_ATTRIBUTES` row plus an arity rule.
        ENTRY POINTS:
          * `Parser._dispatch_toplevel_decl` — top-level declarations
          * `StatementsMixin._parse_attributed_local` — a local `let`/`var`

        Grammar checks only: known name, arity and argument kind, no repeats.
        Position is the caller's (`_reject_misplaced_attributes`); semantic
        rules (`@align`'s power of two and range) are the typechecker's.
        """
        attrs: List[Attribute] = []
        while self.match(TokenType.AT):
            at_tok = self.current()
            self.advance()  # consume '@'
            name_tok = self.expect(TokenType.IDENT, "Expected attribute name after '@'")
            name = name_tok.value
            known = ", ".join("@" + a for a in KNOWN_ATTRIBUTES)
            if name not in KNOWN_ATTRIBUTES:
                self.error(f"unknown attribute `@{name}` (known attributes: {known})")

            arg: Optional[str] = None
            expr_arg = None
            if self.match(TokenType.LPAREN):
                self.advance()  # consume '('
                if name == "align":
                    # `@align(N)` takes a value: a literal, a `static`, or const
                    # arithmetic over either. Folding it needs a namespace the
                    # parser does not have, so the expression travels to the
                    # typechecker as an array length's does.
                    expr_arg = self.parse_expression()
                else:
                    str_tok = self.expect(
                        TokenType.STRING,
                        f"attribute `@{name}` expects a string-literal argument")
                    arg = str_tok.value
                self.expect(TokenType.RPAREN, f"Expected ')' to close `@{name}(...)`")

            # Per-attribute arity/type.
            if name == "section" and arg is None:
                self.error("attribute `@section` requires exactly one "
                           "string-literal argument, e.g. `@section(\".text.boot\")`")
            if name == "synthesize" and arg is not None:
                self.error("attribute `@synthesize` takes no argument")
            if name == "align" and expr_arg is None:
                self.error("attribute `@align` requires exactly one "
                           "constant integer argument, e.g. `@align(8)`")

            # Duplicate attribute is an error.
            for prev in attrs:
                if prev.name == name:
                    self.error(f"duplicate attribute `@{name}`")

            attrs.append(Attribute(name=name, arg=arg, expr_arg=expr_arg,
                                   line=at_tok.line, column=at_tok.column))
            self.skip_newlines()
        return attrs

    def parse_function(self, visibility: Visibility = Visibility.PRIVATE) -> Function:
        start = self.current()
        self.expect(TokenType.FUNC)

        name_token = self.expect(TokenType.IDENT, "Expected function name")
        name = name_token.value

        # Parse optional type parameters: <T, U>
        type_params = self.parse_type_params()

        self.expect(TokenType.LPAREN)
        parameters, _, _ = self.parse_parameters()  # Ignore self_mutable/self_is_reference for regular functions
        self.expect(TokenType.RPAREN)

        # Post-parameter effect slot: `func f(...) unsafe sync [-> T]`. `sync`
        # makes the body a checked suspension-free context; `unsafe` declares
        # that the signature or body touches an unsafe type; `borrows` makes
        # the declaration lend a place of the return type for a window.
        is_consumes, is_unsafe, is_sync, is_borrows = self._parse_effect_slot()
        if is_consumes:
            # `consumes` describes the receiver at the end of the call, and a
            # free function has none.
            self.error(
                "`consumes` may only appear on a method with a `&var self` "
                "receiver — a free function has no receiver to consume. To "
                "take ownership of an argument, declare the parameter by "
                "value and `move` at the call site")

        # Return type (optional, defaults to void)
        return_type = self.parse_return_clause(f"`func {name}`", lends=is_borrows)

        self.skip_newlines()
        body = self.parse_block()

        return Function(
            name=name,
            parameters=parameters,
            return_type=return_type,
            body=body,
            type_params=type_params,
            visibility=visibility,
            is_sync=is_sync,
            is_unsafe=is_unsafe,
            is_borrows=is_borrows,
            line=start.line,
            column=start.column,
            source_file=self.source_file
        )

    def parse_struct(self, visibility: Visibility = Visibility.PRIVATE,
                     is_unsafe: bool = False,
                     is_borrowing: bool = False) -> Struct:
        """Parse a struct declaration: struct Name { field: Type } or struct Box<T> { value: T }

        `unsafe struct` declares an unsafe type: naming, binding, receiving or
        returning one of its values makes a function unsafe. The `Unsafe*` name
        check lives in the typechecker.

        `borrows struct` declares a type that holds a lent place, the one
        declaration that licenses a reference-typed field, because its values
        are confined to one window. Only a shared `&T` field is admitted (see
        `reject_reference_field`); every other rule (at least one reference
        field, the origin, the fence) is the typechecker's (design 275).
        """
        start = self.current()
        self.expect(TokenType.STRUCT)

        name_token = self.expect(TokenType.IDENT, "Expected struct name")
        name = name_token.value

        # Parse optional type parameters: <T, U>
        type_params = self.parse_type_params()

        self.skip_newlines()
        self.expect(TokenType.LBRACE)
        self.skip_newlines()

        fields = []
        while not self.match(TokenType.RBRACE, TokenType.EOF):
            field_doc = self.doc_text(self._take_doc())
            # Member visibility: an optional `public` / `public(package)` /
            # `public(parent)` / `private` modifier precedes the field name. A
            # bare field inherits its declaring type's tier, so the parser
            # records (tier, was-one-written) and `effective_field_visibility`
            # decides what it means.
            if self.match(TokenType.AT):
                # An `@align` on a field would be the type-carried form, which
                # does not exist yet (DF-300b); the funnel says so by name.
                self._reject_attribute_position("struct fields")
            field_visibility, field_vis_written = self._parse_field_visibility()
            field_name_token = self.expect(TokenType.IDENT, "Expected field name")
            self.expect(TokenType.COLON, "Expected ':' after field name")
            type_anchor = self.current()
            field_type = self.parse_type()
            # A field may not name a reference, except a `borrows struct`'s
            # shared reference field (see `reject_reference_field`).
            self.reject_reference_field(field_name_token.value, name,
                                        field_type, type_anchor,
                                        borrowing_struct=is_borrowing)
            fields.append(StructField(name=field_name_token.value, type=field_type,
                                      visibility=field_visibility,
                                      visibility_written=field_vis_written,
                                      line=field_name_token.line,
                                      column=field_name_token.column,
                                      doc=field_doc))

            self.skip_newlines()
            # Allow optional comma
            if self.match(TokenType.COMMA):
                self.advance()
            self.skip_newlines()

        self.expect(TokenType.RBRACE)

        return Struct(
            name=name,
            fields=fields,
            type_params=type_params,
            visibility=visibility,
            is_unsafe=is_unsafe,
            is_borrowing=is_borrowing,
            line=start.line,
            column=start.column,
            source_file=self.source_file
        )

    def parse_enum(self, visibility: Visibility = Visibility.PRIVATE) -> Enum:
        """Parse an enum declaration: enum Name { case Variant1 } or enum Option<T> { case Some(value: T) }"""
        start = self.current()
        self.expect(TokenType.ENUM)

        name_token = self.expect(TokenType.IDENT, "Expected enum name")
        name = name_token.value

        # Parse optional type parameters: <T, U>
        type_params = self.parse_type_params()

        # Raw integer backing: `enum SysError: UInt8`.
        raw_type = None
        if self.match(TokenType.COLON):
            self.advance()
            raw_type = self.parse_type()

        self.skip_newlines()
        self.expect(TokenType.LBRACE)
        self.skip_newlines()

        variants = []
        while not self.match(TokenType.RBRACE, TokenType.EOF):
            variant_doc = self.doc_text(self._take_doc())
            self.expect(TokenType.CASE, "Expected 'case' keyword for enum variant")

            variant_name_token = self.expect(TokenType.IDENT, "Expected variant name")
            variant_name = variant_name_token.value

            # Parse optional associated values: (name: Type, ...)
            associated_types = []
            if self.match(TokenType.LPAREN):
                self.advance()

                def _parse_payload():
                    # A payload is storage on the same terms a struct field is,
                    # so it may not name a reference either.
                    p_name = self.expect(TokenType.IDENT,
                                         "Expected parameter name").value
                    self.expect(TokenType.COLON,
                                "Expected ':' after parameter name")
                    p_anchor = self.current()
                    p_type = self.parse_type()
                    self.reject_reference_payload(p_name, variant_name, name,
                                                  p_type, p_anchor)
                    associated_types.append((p_name, p_type))

                if not self.match(TokenType.RPAREN):
                    _parse_payload()

                    # Parse additional parameters
                    while self.match(TokenType.COMMA):
                        self.advance()
                        # Trailing comma.
                        if self.match(TokenType.RPAREN):
                            break
                        _parse_payload()

                self.expect(TokenType.RPAREN)

            # Explicit raw value: `case Ok = 0`. Parsed wherever it is
            # written; whether it is required (a backing is declared) or
            # forbidden is the typechecker's call, so the diagnostic can name
            # the enum and the rule together.
            raw_value = None
            raw_value_expr = None
            raw_line = 0
            raw_column = 0
            if self.match(TokenType.ASSIGN):
                assign_tok = self.current()
                self.advance()
                raw_line = assign_tok.line
                raw_column = assign_tok.column
                # The slot takes a const expression, so a flags enum can say
                # which bit it means (`case ThreadCreate = 1 << 8`). Only a
                # literal, bare or negated, is decoded here; anything else is
                # kept as an expression and folded by `_fold_enum_raw_values`
                # before registration. The literal fast path spares the common
                # `case A = 0` a fold.
                if (self.match(TokenType.INT)
                        and self._raw_value_ends_at(1)):
                    value_tok = self.advance()
                    # Through the shared decoder, never `int()`: an INT token
                    # keeps its prefix (`0x100`).
                    raw_value = self._decode_int_literal(value_tok.value)
                elif (self.match(TokenType.MINUS)
                        and self.peek(1).type == TokenType.INT
                        and self._raw_value_ends_at(2)):
                    self.advance()
                    value_tok = self.advance()
                    raw_value = -self._decode_int_literal(value_tok.value)
                else:
                    raw_value_expr = self.parse_expression()

            variants.append(EnumVariant(name=variant_name,
                                        associated_types=associated_types,
                                        doc=variant_doc,
                                        raw_value=raw_value,
                                        raw_value_expr=raw_value_expr,
                                        raw_line=raw_line,
                                        raw_column=raw_column))

            self.skip_newlines()
            # Allow optional comma
            if self.match(TokenType.COMMA):
                self.advance()
            self.skip_newlines()

        self.expect(TokenType.RBRACE)

        return Enum(
            name=name,
            variants=variants,
            type_params=type_params,
            visibility=visibility,
            line=start.line,
            column=start.column,
            source_file=self.source_file,
            raw_type=raw_type
        )

    def _raw_value_ends_at(self, offset: int) -> bool:
        """Would an enum raw value end at `offset` tokens from here?

        The literal fast path in `parse_enum` may claim its tokens only if
        nothing follows that could continue an expression; otherwise
        `case A = 1 << 0` would take the `1` and leave `<< 0` to be misread as
        the next variant. A variant ends at a comma, a newline, or the enum's
        closing brace.
        """
        t = self.peek(offset).type
        return t in (TokenType.COMMA, TokenType.NEWLINE, TokenType.RBRACE,
                     TokenType.EOF)

    def parse_trait(self, visibility: Visibility = Visibility.PRIVATE) -> Trait:
        """Parse trait declaration: trait Copy: Deinit { func copy(self) -> Self }"""
        start = self.current()
        self.expect(TokenType.TRAIT)

        name_token = self.expect(TokenType.IDENT, "Expected trait name")
        name = name_token.value

        # Parse optional type parameters
        type_params = self.parse_type_params()

        # Parse optional parent traits: `: ParentTrait, AnotherTrait`
        parent_traits = []
        if self.match(TokenType.COLON):
            self.advance()
            # Parse first parent trait
            parent_token = self.expect(TokenType.IDENT, "Expected parent trait name")
            parent_traits.append(parent_token.value)
            # Parse additional parent traits (comma-separated)
            while self.match(TokenType.COMMA):
                self.advance()
                parent_token = self.expect(TokenType.IDENT, "Expected parent trait name")
                parent_traits.append(parent_token.value)

        self.skip_newlines()
        self.expect(TokenType.LBRACE)
        self.skip_newlines()

        methods = []
        associated_types = []
        # A trait body is a requirement list, newline-separated like module
        # scope, so its gaps go through the same chokepoint.
        self.expect_statement_end()
        while not self.match(TokenType.RBRACE, TokenType.EOF):
            member_start = self.current()
            member_doc = self._take_doc()
            # A trait requirement carries no visibility of its own (the trait's
            # tier is the bar), so `private` here is the same misuse.
            self._reject_private_modifier()
            if self.at_type_alias_start():
                # Parse associated type: type Item
                assoc_type = self.parse_associated_type()
                associated_types.append(assoc_type)
                if member_doc is not None:
                    # Associated types carry no doc slot; report rather than drop.
                    self._release_doc(member_doc)
            elif self.match(TokenType.FUNC, TokenType.UNSAFE, TokenType.STATIC):
                # A static requirement spells the keyword too, so a reader of
                # the trait sees which requirements are called on the type. A
                # prefix `unsafe` reaches here only to be reported; the effect
                # goes after the parameter list.
                declared_static = self._parse_static_modifier()
                if self._parse_unsafe_modifier():
                    self._error_unsafe_prefix()
                if declared_static and not self.match(TokenType.FUNC):
                    self.error(
                        "Expected 'func' after 'static' in trait — `static` "
                        "marks a static REQUIREMENT (design 236), one called "
                        "on the type rather than on a receiver")
                method = self.parse_trait_method(declared_static)
                method.doc = self.doc_text(member_doc)
                methods.append(method)
            else:
                self.error(f"Expected 'type' or 'func' in trait, got {self.current().type.name}")
            self.expect_statement_end(member_start, declarations=True)

        self.expect(TokenType.RBRACE)

        return Trait(
            name=name,
            methods=methods,
            associated_types=associated_types,
            type_params=type_params,
            parent_traits=parent_traits,
            visibility=visibility,
            line=start.line,
            column=start.column,
            source_file=self.source_file
        )

    def parse_associated_type(self) -> AssociatedType:
        """Parse associated type declaration: type Item"""
        start = self.current()
        self.expect_ident('type')

        name_token = self.expect(TokenType.IDENT, "Expected associated type name")

        return AssociatedType(
            name=name_token.value,
            line=start.line,
            column=start.column
        )

    def parse_trait_method(self, declared_static: bool = False) -> TraitMethod:
        """Parse method signature in trait: func name(&self, params...) -> Type

        `declared_static` is the member-head `static` keyword the caller already
        consumed.
        """
        start = self.current()
        self.expect(TokenType.FUNC, "Expected 'func' in trait method")

        name_token = self.expect(TokenType.IDENT, "Expected method name")
        name = name_token.value

        self.expect(TokenType.LPAREN)
        parameters, self_mutable, self_is_reference = self.parse_parameters()
        self.expect(TokenType.RPAREN)

        self._check_static_declaration(
            name, declared_static,
            has_receiver=any(p.name == "self" for p in parameters),
            is_init=False, kind="trait requirement", anchor=start)

        # Post-parameter effect slot: `func m(...) unsafe sync -> T`. A `sync`
        # requirement stays sync-callable through `any` once erased; an
        # `unsafe` requirement states the effect once for every conformer.
        is_consumes, is_unsafe, is_sync, is_borrows = self._parse_effect_slot()
        if is_consumes:
            # No trait participation: a call through an erased `any Trait`
            # receiver has no binding behind the existential to retire
            # (design 260).
            self.error(
                "`consumes` may not appear on a trait requirement (design 260 "
                "v1): the transfer is spelled at the CALL (`(move x).m()`), "
                "and an erased `any Trait` receiver has no binding to retire. "
                "Declare the consuming method on the concrete type instead")
        if is_borrows:
            # No trait participation: a `borrows` requirement would need a
            # place-shaped call through an erased receiver (design 141).
            self.error(
                "`borrows` may not appear on a trait requirement (design 141 "
                "v1): a place is not a value, so it cannot be yielded through "
                "an erased `any Trait` receiver. Declare the borrows method on "
                "the concrete type instead")

        # Return type (optional, defaults to void)
        return_type = self.parse_return_clause(f"trait method `{name}`")

        # Optional default body: `func m(...) -> T { ... }`; conformers may
        # omit or override it. A newline may separate the signature from the
        # `{`, so peek across newlines, and rewind if no `{` follows (the next
        # member starts on the following line).
        body = None
        save_pos = self.pos
        self.skip_newlines()
        if self.match(TokenType.LBRACE):
            body = self.parse_block()
        else:
            self.pos = save_pos

        return TraitMethod(
            name=name,
            parameters=parameters,
            return_type=return_type,
            self_mutable=self_mutable,
            self_is_reference=self_is_reference,
            is_sync=is_sync,
            is_unsafe=is_unsafe,
            is_static=declared_static,
            body=body,
            line=start.line,
            column=start.column
        )

    def parse_extension(self) -> Extension:
        """Parse extension declaration: extension Box<T>: Trait { type Item = Int; func... }

        For generic extensions like `extension Vector<T>`, the typechecker will determine
        that T is not a known type and treat it as a type parameter.
        For specialized extensions like `extension Vector<String>`, String is a known type
        so it's treated as a type argument (specialization).

        Takes no visibility: an extension head cannot carry one (see
        `_error_extension_visibility`), and every caller has already refused
        the modifier.
        """
        start = self.current()
        self.expect(TokenType.EXTENSION)

        # Accept identifiers (type names like String, Int, Vector are all identifiers now)
        if self.match(TokenType.IDENT):
            name_token = self.advance()
            struct_name = name_token.value
        elif self.match(TokenType.LBRACKET):
            # Extensions on fixed-array types (`extension [Int; 8]`) are not
            # supported; `.len()` and `.swap(i, j)` are the whole array surface.
            self.error("extension methods on array types are not supported; "
                       "fixed arrays have the builtin `.len()` and `.swap(i, j)` only")
        else:
            self.error("Expected type name after 'extension'")

        # Optional type parameters or type arguments: <T, U> or <String, Int>.
        # Parsed as type_params; the typechecker decides which reading is
        # correct by namespace lookup.
        type_params = []
        type_args = []

        if self.match(TokenType.LT):
            type_params = self.parse_type_params()

        # Parse optional trait conformances: `: Trait1, Trait2` or `: module.Trait`
        conformances = []
        if self.match(TokenType.COLON):
            self.advance()
            # Parse first trait name (may be module-qualified: lib.Trait)
            trait_name = self._parse_qualified_name("Expected trait name after ':'")
            conformances.append(trait_name)
            # Parse additional traits
            while self.match(TokenType.COMMA):
                self.advance()
                trait_name = self._parse_qualified_name("Expected trait name after ','")
                conformances.append(trait_name)

        self.skip_newlines()
        self.expect(TokenType.LBRACE)
        self.skip_newlines()

        methods = []
        type_assignments = []
        # An extension body is a member list, newline-separated like module
        # scope, so its gaps go through the same chokepoint.
        self.expect_statement_end()
        while not self.match(TokenType.RBRACE, TokenType.EOF):
            member_start = self.current()
            member_doc = self._take_doc()
            # Checked at the member head, ahead of the kind dispatch, which
            # would only report it as "expected `func`".
            self._reject_private_modifier()
            if self.at_type_alias_start():
                # Parse type assignment: type Item = Int
                type_assign = self.parse_type_assignment()
                type_assignments.append(type_assign)
                if member_doc is not None:
                    # Type assignments carry no doc slot; report rather than drop.
                    self._release_doc(member_doc)
            elif self.match(TokenType.PUBLIC, TokenType.FUNC, TokenType.INIT,
                            TokenType.UNSAFE, TokenType.STATIC):
                # A member head, in its one order: `public static func ...`.
                # `static` marks a static method; a member head only continues
                # into `func`, so it never meets a module-level `static`
                # variable. A prefix `unsafe` reaches here only to be reported
                # against the effect slot.
                method_visibility = Visibility.PRIVATE
                had_visibility = self.match(TokenType.PUBLIC)
                if had_visibility:
                    method_visibility = self._parse_visibility()
                declared_static = self._parse_static_modifier()
                if self._parse_unsafe_modifier():
                    self._error_unsafe_prefix()
                if not self.match(TokenType.FUNC, TokenType.INIT):
                    if declared_static and self.match(TokenType.PUBLIC):
                        self.error(
                            "the visibility modifier comes first — write "
                            "`public static func ...`, not `static public "
                            "func ...`")
                    if declared_static:
                        self.error(
                            "Expected 'func' after 'static' in extension — "
                            "`static` marks a static METHOD (design 236); a "
                            "module-level `static` variable is declared "
                            "outside the extension")
                    self.error("Expected 'func' or 'init' after visibility modifier "
                               "in extension")
                method = self.parse_method(method_visibility, declared_static)
                method.doc = self.doc_text(member_doc)
                methods.append(method)
            elif self.match(TokenType.AT):
                # Attributes are legal on a top-level func/static, an extension
                # head and a local `let`/`var`; never on a method.
                self._reject_attribute_position("methods")
            else:
                self.error(f"Expected 'type', 'func', or 'init' in extension, got {self.current().type.name}")
            self.expect_statement_end(member_start, declarations=True)

        self.expect(TokenType.RBRACE)

        return Extension(
            struct_name=struct_name,
            methods=methods,
            type_params=type_params,
            conformances=conformances,
            type_assignments=type_assignments,
            line=start.line,
            column=start.column,
            source_file=self.source_file
        )

    def parse_type_assignment(self) -> TypeAssignment:
        """Parse type assignment: type Item = Int"""
        start = self.current()
        self.expect_ident('type')

        name_token = self.expect(TokenType.IDENT, "Expected associated type name")
        self.expect(TokenType.ASSIGN, "Expected '=' after associated type name")
        assigned_type = self.parse_type()

        return TypeAssignment(
            name=name_token.value,
            assigned_type=assigned_type,
            line=start.line,
            column=start.column
        )

    def parse_type_definition(self, visibility: Visibility = Visibility.PRIVATE) -> TypeDefinition:
        """Parse top-level type definition: type MyInt = Int"""
        start = self.current()
        self.expect_ident('type')

        name_token = self.expect(TokenType.IDENT, "Expected type name")
        self.expect(TokenType.ASSIGN, "Expected '=' after type name")
        defined_type = self.parse_type()

        return TypeDefinition(
            name=name_token.value,
            defined_type=defined_type,
            visibility=visibility,
            line=start.line,
            column=start.column,
            source_file=self.source_file
        )

    def parse_static(self, visibility: Visibility = Visibility.PRIVATE,
                     is_unsafe: bool = False) -> 'StaticDecl':
        """Parse a module-level static declaration:

            static NAME: Type = initializer
            static NAME: Type                   (bare zero-init)
            unsafe static var NAME: Type = init (mutable)

        The initializer is optional for zero-init POD and fixed-array statics;
        the typechecker enforces the const-init, Sync-only and destructibility
        constraints.

        `var` and `unsafe` come as a pair: compound global state is consistent
        only by a serialization argument the compiler cannot see, and `unsafe`
        forces every touching function to state that it owns one. Either half
        alone is a clean error naming the spelling (design 149).
        """
        start = self.current()
        self.expect(TokenType.STATIC)

        is_var = False
        if self.match(TokenType.VAR):
            self.advance()
            is_var = True
            if not is_unsafe:
                self.error("a mutable static is declared `unsafe static var` — "
                           "write `unsafe static var` here, or drop `var` for an "
                           "immutable static (single-word state that several "
                           "tasks update independently wants `Atomic`, not this)")
        elif is_unsafe:
            self.error("`unsafe` on a static marks a MUTABLE one — write "
                       "`unsafe static var NAME: T = ...`, or drop `unsafe` "
                       "for an immutable static, which needs no claim from you")

        name_token = self.expect(TokenType.IDENT, "Expected static name")
        self.expect(TokenType.COLON, "Expected ':' after static name")
        static_type = self.parse_type()

        initializer = None
        if self.match(TokenType.ASSIGN):
            self.advance()  # consume '='
            initializer = self.parse_expression()

        return StaticDecl(
            name=name_token.value,
            type=static_type,
            initializer=initializer,
            visibility=visibility,
            is_var=is_var,
            is_unsafe=is_unsafe,
            line=start.line,
            column=start.column,
            source_file=self.source_file
        )

    def parse_extern_block(self) -> ExternBlock:
        """Parse extern "C" { func declarations... }"""
        start = self.current()
        self.expect(TokenType.EXTERN)

        # Expect ABI string (only "C" supported for now)
        abi_token = self.expect(TokenType.STRING, "Expected ABI string after 'extern'")
        abi = abi_token.value
        if abi != "C":
            self.error(f"Unsupported ABI: '{abi}' (only 'C' is supported)")

        self.skip_newlines()
        self.expect(TokenType.LBRACE)
        self.skip_newlines()

        functions = []
        # An `extern "C" { }` block is a declaration list, newline-separated
        # like module scope, so its gaps go through the same chokepoint.
        self.expect_statement_end()
        while not self.match(TokenType.RBRACE, TokenType.EOF):
            decl_start = self.current()
            functions.append(self.parse_extern_function())
            self.expect_statement_end(decl_start, declarations=True)

        self.expect(TokenType.RBRACE)

        return ExternBlock(
            abi=abi,
            functions=functions,
            line=start.line,
            column=start.column
        )

    def parse_extern_function(self) -> ExternFunction:
        """Parse external function declaration: [blocking] func name(params, ...) -> ReturnType"""
        start = self.current()
        # `extern blocking func`: an unbounded FFI call, run via thread offload
        # and treated as a suspension source. `blocking` is a soft keyword
        # valid only here.
        is_blocking = False
        if self.match_ident("blocking"):
            is_blocking = True
            self.advance()
        self.expect(TokenType.FUNC, "Expected 'func' in extern block")

        name_token = self.expect(TokenType.IDENT, "Expected function name")
        name = name_token.value

        self.expect(TokenType.LPAREN)
        parameters, _, _ = self.parse_parameters()

        # Check for variadic marker (...)
        is_variadic = False
        if self.match(TokenType.ELLIPSIS):
            is_variadic = True
            self.advance()
        elif self.match(TokenType.COMMA):
            # Handle: func open(path: P, flags: I, ...) case
            self.advance()
            if self.match(TokenType.ELLIPSIS):
                is_variadic = True
                self.advance()

        self.expect(TokenType.RPAREN)

        # Return type (optional, defaults to void)
        return_type = self.parse_return_clause(f"`extern func {name}`")

        return ExternFunction(
            name=name,
            parameters=parameters,
            return_type=return_type,
            is_variadic=is_variadic,
            is_blocking=is_blocking,
            line=start.line,
            column=start.column,
            source_file=self.source_file
        )

    def _parse_static_modifier(self) -> bool:
        """Consume a member-head `static`, if present.

        It never collides with a module-level `static` variable: a declaration
        head continues into a name and a colon (`static PAGE_SIZE: Int = 4096`)
        while a member head continues into `func`, and only extension and trait
        bodies reach this.
        """
        if self.match(TokenType.STATIC):
            self.advance()
            return True
        return False

    def _check_static_declaration(self, name: str, declared_static: bool,
                                  has_receiver: bool, is_init: bool,
                                  kind: str, anchor) -> None:
        """The `static` keyword and the receiver must agree (design 236).

        Staticness could be inferred from the missing receiver, but
        reader-visibility wins: without the keyword, a forgotten `&self`
        silently turns an instance method into a static one. The keyword makes
        that the right error at the right place.

        ENTRY POINTS (the only places a method-shaped declaration is parsed):
          * `parse_method`       — every extension member, struct and enum,
                                   `init` included so it can be refused
          * `parse_trait_method` — every trait requirement
        Module-level `func`s and compiler-synthesized Methods never reach here.
        """
        if is_init:
            if declared_static:
                self.error_at(
                    anchor,
                    "`init` may not be declared `static` — an initializer takes "
                    "no receiver by construction, and `Type(...)` is how it is "
                    "called. Remove the `static`")
            return
        if declared_static and has_receiver:
            self.error_at(
                anchor,
                f"{kind} `{name}` is declared `static` but takes a receiver — "
                f"remove the `static`, or drop the `&self`/`&var self` "
                f"parameter if a static was intended")
        if not declared_static and not has_receiver:
            self.error_at(
                anchor,
                f"{kind} `{name}` has no receiver — add `&self`/`&var self`, "
                f"or declare it `static func` if a static was intended")

    def parse_method(self, visibility: Visibility = Visibility.PRIVATE,
                     declared_static: bool = False) -> Method:
        """Parse method definition: func name(&self, ...) -> Type { ... }
           or init method: init(...) { ... }

        `declared_static` is the member-head `static` keyword the caller already
        consumed.
        """
        start = self.current()

        # Check if it's an init method
        is_init = False
        type_params = []
        if self.match(TokenType.INIT):
            is_init = True
            name = "init"
            self.advance()
        elif self.match(TokenType.FUNC):
            self.advance()
            if self.match(TokenType.LBRACKET):
                # Subscript: `func [](&self, i: Int) borrows -> T`. The method's
                # name is the string "[]", reachable only through `v[i]` sugar;
                # the symbol tables key methods by plain string, so nothing
                # downstream needs to know.
                open_tok = self.advance()
                self.expect(TokenType.RBRACKET,
                            "Expected `]` to close the subscript method name "
                            "`[]` — the name is the two brackets with nothing "
                            "between them")
                name = "[]"
                name_token = open_tok
            else:
                name_token = self.expect(TokenType.IDENT, "Expected method name")
                name = name_token.value
            # Method-level generic type parameters: `func map<U>(...)`, in
            # addition to the extension's own (the `T` in `extension
            # Vector<T>`). `init` takes none; it constructs the extension's
            # type.
            type_params = self.parse_type_params()
        else:
            self.error("Expected 'func' or 'init' in extension")

        self.expect(TokenType.LPAREN)
        parameters, self_mutable, self_is_reference, is_static = self.parse_method_parameters()
        self.expect(TokenType.RPAREN)

        self._check_static_declaration(
            name, declared_static, has_receiver=not is_static,
            is_init=is_init, kind="method", anchor=start)

        # Post-parameter effect slot, as for a free function; see
        # `parse_function`.
        is_consumes, is_unsafe, is_sync, is_borrows = self._parse_effect_slot()
        # `consumes` ends a `&var self` borrow in the value's death, so it
        # needs a receiver, an exclusive one, and cannot be combined with
        # lending one out (design 260).
        if is_consumes and (is_static or is_init):
            what = "an `init`" if is_init else "a `static` method"
            self.error(
                f"`consumes` may only appear on a method with a `&var self` "
                f"receiver — {what} has no receiver to consume")
        if is_consumes and not self_mutable:
            self.error(
                "a consuming method needs an exclusive receiver — write "
                "`&var self`. `consumes` ends the borrow in the value's death, "
                "and a shared `&self` promises the caller the opposite")
        if is_consumes and is_borrows:
            self.error(
                "`consumes` and `borrows` are mutually exclusive — you cannot "
                "lend out storage from a receiver you destroyed. Write one or "
                "the other")
        if is_borrows and is_init:
            self.error(
                "`init` may not be `borrows` — an initializer CONSTRUCTS a "
                "value, and there is no prior storage for it to lend")
        if name == "[]" and not is_borrows:
            self.error(
                "a `[]` subscript must be `borrows` — `v[i]` names a PLACE in "
                "the container, not a value read out of it. Write "
                "`func [](&var self, ...) borrows -> &var T`; a value-returning lookup "
                "is an ordinary named method")

        # Return type (optional, defaults to void)
        return_type = self.parse_return_clause(
            "`init`" if is_init else f"method `{name}`", lends=is_borrows)

        self.skip_newlines()
        body = self.parse_block()

        return Method(
            name=name,
            parameters=parameters,
            return_type=return_type,
            body=body,
            is_init=is_init,
            self_mutable=self_mutable,
            self_is_reference=self_is_reference,
            is_static=is_static,
            declared_static=declared_static,
            is_sync=is_sync,
            is_unsafe=is_unsafe,
            is_borrows=is_borrows,
            is_consumes=is_consumes,
            type_params=type_params,
            visibility=visibility,
            line=start.line,
            column=start.column,
            source_file=self.source_file
        )

    def parse_method_parameters(self):
        """Parse method parameters. Returns (params, self_mutable, self_is_reference, is_static).

        - is_static is True if no 'self' parameter is present (static method)
        - self_mutable is True if '&var self' is used
        - self_is_reference is True if '&self' or '&var self' is used
        """
        params, self_mutable, self_is_reference = self.parse_parameters()

        # Check if this is a static method (no self parameter)
        is_static = True
        if params and params[0].name == 'self':
            is_static = False

        return params, self_mutable, self_is_reference, is_static

    def parse_parameters(self):
        """Parse parameters. Returns (params, self_mutable, self_is_reference).

        - self_mutable is True if '&var self' is used
        - self_is_reference is True if '&self' or '&var self' is used
        """
        params = []
        self_mutable = False
        self_is_reference = False

        if self.match(TokenType.RPAREN):
            return params, self_mutable, self_is_reference

        while True:
            if self.match(TokenType.AT):
                # Same answer a field gets: a parameter's alignment is a
                # property of its type, which cannot be spelled yet (DF-300b).
                self._reject_attribute_position("parameters")

            # Check for '&' before parameter (for reference parameters and &self/&var self)
            is_ref = False
            is_var = False

            if self.match(TokenType.AMPERSAND):
                is_ref = True
                self.advance()
                # Check for &var (mutable reference)
                if self.match(TokenType.VAR):
                    is_var = True
                    self.advance()
            elif self.match(TokenType.VAR):
                # `var self` is refused: both receivers are borrows and the
                # sigil says so, while a bare `var self` reads like a by-value
                # consuming receiver.
                if self.peek(1).type == TokenType.SELF:
                    self.error(
                        "`var self` is not a receiver spelling: write "
                        "`&var self` to borrow mutably (or `&self` to borrow "
                        "immutably)")
                is_var = True
                is_ref = True  # Implied reference
                self.advance()

            # Allow both IDENT and SELF as parameter names (for method self parameter)
            if self.match(TokenType.IDENT, TokenType.SELF):
                name_token = self.advance()
            else:
                self.error("Expected parameter name")

            # Special case: 'self' doesn't need type annotation (type is inferred from extension)
            if name_token.value == "self":
                if not is_ref:
                    self.error("'self' must be a reference: use '&self' or '&var self'")
                if len(params) != 0:
                    self.error("'self' can only be the first parameter")
                self_mutable = is_var
                self_is_reference = True
                # Create a placeholder type - will be filled in by type checker
                param_type = SawType(TypeKind.VOID)  # Placeholder
                params.append(Parameter(
                    name=name_token.value,
                    type=param_type,
                    is_reference=True,
                    reference_mutable=is_var
                ))
            else:
                # Regular parameter - reference is indicated by type annotation, not prefix
                if is_ref:
                    self.error("Use reference type annotation (e.g., 'x: &Int') instead of '&x'")
                self.expect(TokenType.COLON, "Expected ':' after parameter name")
                param_type = self.parse_type()

                # Check if the type is a reference type
                param_is_ref = param_type.kind == TypeKind.REFERENCE
                param_ref_mut = param_is_ref and param_type.reference_mutable

                # Check for default value: param: Type = expr
                default_value = None
                if self.match(TokenType.ASSIGN):
                    self.advance()  # consume '='
                    default_value = self.parse_expression()

                params.append(Parameter(
                    name=name_token.value,
                    type=param_type,
                    default_value=default_value,
                    is_reference=param_is_ref,
                    reference_mutable=param_ref_mut
                ))

            if not self.match(TokenType.COMMA):
                break
            self.advance()  # consume comma

            # Trailing comma, for one-parameter-per-line wrapping.
            if self.match(TokenType.RPAREN):
                break

            # Check for variadic marker (...) - stop parsing parameters
            if self.match(TokenType.ELLIPSIS):
                break

        return params, self_mutable, self_is_reference

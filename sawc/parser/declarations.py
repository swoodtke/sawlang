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
        """Parse zero or more attribute lines (design 58): `@name` or
        `@name("string")`, each immediately preceding a declaration.

        Grammar-level checks live here (Part 1): the name must be a known
        attribute, `@export` takes zero args or one string literal, `@section`
        requires exactly one string literal, `@synthesize` takes none, and an
        attribute may not repeat. Position (which declaration kinds accept
        which attribute) and semantic rules are enforced by the caller and the
        typechecker respectively.
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
            if self.match(TokenType.LPAREN):
                self.advance()  # consume '('
                str_tok = self.expect(
                    TokenType.STRING,
                    f"attribute `@{name}` expects a string-literal argument")
                arg = str_tok.value
                self.expect(TokenType.RPAREN, f"Expected ')' to close `@{name}(...)`")

            # Per-attribute arity/type (Part 1).
            if name == "section" and arg is None:
                self.error("attribute `@section` requires exactly one "
                           "string-literal argument, e.g. `@section(\".text.boot\")`")
            if name == "synthesize" and arg is not None:
                self.error("attribute `@synthesize` takes no argument")

            # Duplicate attribute is an error.
            for prev in attrs:
                if prev.name == name:
                    self.error(f"duplicate attribute `@{name}`")

            attrs.append(Attribute(name=name, arg=arg,
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

        # Post-parameter effect slot (designs 18/22, design 136):
        # `func f(...) unsafe sync [-> T]`. `sync` makes the body a checked
        # suspension-free context; `unsafe` declares that the signature or body
        # touches an unsafe type (design 130's trigger rule). The slot spells the
        # effects exactly as the matching function TYPE does. `borrows` (design
        # 141) makes the declaration yield a PLACE of the return type for a
        # window instead of a value.
        is_unsafe, is_sync, is_borrows = self._parse_effect_slot()

        # Return type (optional, defaults to void)
        return_type = self.parse_return_clause(f"`func {name}`")

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
                     is_unsafe: bool = False) -> Struct:
        """Parse a struct declaration: struct Name { field: Type } or struct Box<T> { value: T }

        `unsafe struct` (design 130) declares an unsafe TYPE: naming, binding,
        receiving or returning one of its values makes a function unsafe. The
        name check (`Unsafe*`) is a semantic rule and lives in the typechecker.
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
            # Member visibility (design 80): an optional `public` /
            # `public(package)` / `public(parent)` modifier precedes the field
            # name; omitted means private-by-default outside the defining module.
            field_visibility = self._parse_visibility()
            field_name_token = self.expect(TokenType.IDENT, "Expected field name")
            self.expect(TokenType.COLON, "Expected ':' after field name")
            type_anchor = self.current()
            field_type = self.parse_type()
            # A field is storage that outlives every call, so it may not name a
            # reference (DF-163d) — and refusing the declaration is what closes
            # the struct-literal construction `Holder(r: &x)` with it.
            self.reject_reference_field(field_name_token.value, name,
                                        field_type, type_anchor)
            fields.append(StructField(name=field_name_token.value, type=field_type,
                                      visibility=field_visibility,
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

        # Raw integer backing (design 145 unit B2): `enum SysError: UInt8`.
        # Reuses the existing COLON token, so both lexers are untouched.
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
                    # so it may not name a reference either (DF-188a).
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
                        # Trailing comma (design 129).
                        if self.match(TokenType.RPAREN):
                            break
                        _parse_payload()

                self.expect(TokenType.RPAREN)

            # Explicit raw value (design 145 unit B2): `case Ok = 0`. Parsed
            # wherever it is written; whether it is REQUIRED (a backing is
            # declared) or forbidden (none is) is the typechecker's call, so the
            # diagnostic can name the enum and the rule together.
            raw_value = None
            raw_value_expr = None
            raw_line = 0
            raw_column = 0
            if self.match(TokenType.ASSIGN):
                assign_tok = self.current()
                self.advance()
                raw_line = assign_tok.line
                raw_column = assign_tok.column
                # DF-232c: the slot takes a CONST EXPRESSION, so a flags enum
                # can say which bit it means (`case ThreadCreate = 1 << 8`).
                # Only a literal — bare or negated — is decoded here; anything
                # else is kept as an expression and folded before registration
                # by `_fold_enum_raw_values`, which is the earliest point the
                # value is read. Keeping the literal fast path means the
                # overwhelmingly common `case A = 0` costs no fold and behaves
                # exactly as it did.
                if (self.match(TokenType.INT)
                        and self._raw_value_ends_at(1)):
                    value_tok = self.advance()
                    # DF-185a: through the shared decoder, not `int()`. An INT
                    # token keeps its canonical text, prefix and all, so a hex
                    # or binary raw value — `case Debug = 0x100`, the way a
                    # wire table is actually written — died here as an uncaught
                    # `invalid literal for int() with base 10: '0x100'`.
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
        """Would an enum raw value END at `offset` tokens from here (DF-232c)?

        The literal fast path in `parse_enum` may only claim the tokens it sees
        if nothing follows that could CONTINUE an expression — otherwise
        `case A = 1 << 0` would take the `1` and leave `<< 0` to be mistaken for
        the next variant, which is exactly the `Expected 'case' keyword` error
        this finding was filed on. A variant ends at a comma, a newline, or the
        enum's closing brace.
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
        while not self.match(TokenType.RBRACE, TokenType.EOF):
            member_doc = self._take_doc()
            if self.at_type_alias_start():
                # Parse associated type: type Item
                assoc_type = self.parse_associated_type()
                associated_types.append(assoc_type)
                if member_doc is not None:
                    # Associated types carry no doc slot; report rather than drop.
                    self._release_doc(member_doc)
            elif self.match(TokenType.FUNC, TokenType.UNSAFE, TokenType.STATIC):
                # design 236: a STATIC requirement spells the keyword too, so a
                # reader of the trait sees which requirements are called on the
                # type. A prefix `unsafe` reaches here only to be reported: a
                # trait requirement spells the effect after its parameter list,
                # like every other signature (design 136).
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
            self.skip_newlines()

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
        consumed (design 236).
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

        # Post-parameter effect slot (designs 22/16/51, design 136):
        # `func m(...) unsafe sync -> T`. A `sync` trait method is a checked
        # suspension-free context — and, once erased, stays sync-callable through
        # `any` (the effect follows the trait signature). An `unsafe` requirement
        # states the effect once for every conformer.
        is_unsafe, is_sync, is_borrows = self._parse_effect_slot()
        if is_borrows:
            # v1 fence (design 141): no trait participation. A `borrows`
            # requirement means "every conformer yields a place", which needs a
            # place-shaped call through an erased receiver — the generic
            # `T: IndexPlace` follow-up.
            self.error(
                "`borrows` may not appear on a trait requirement (design 141 "
                "v1): a place is not a value, so it cannot be yielded through "
                "an erased `any Trait` receiver. Declare the borrows method on "
                "the concrete type instead")

        # Return type (optional, defaults to void)
        return_type = self.parse_return_clause(f"trait method `{name}`")

        # Optional default body (design 56): `func m(...) -> T { ... }`. A trait
        # method WITH a body is a default; conformers may omit or override it.
        # A newline may separate the signature from the `{`, so skip newlines
        # before peeking — but only commit to a body if a `{` actually follows
        # (otherwise the next trait member starts on the following line).
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

        Takes no visibility: an extension head cannot carry one (ruled Aug 20 —
        see `_error_extension_visibility`), and every caller reaching this point
        has already refused the modifier.
        """
        start = self.current()
        self.expect(TokenType.EXTENSION)

        # Accept identifiers (type names like String, Int, Vector are all identifiers now)
        if self.match(TokenType.IDENT):
            name_token = self.advance()
            struct_name = name_token.value
        elif self.match(TokenType.LBRACKET):
            # design 72 L12: extensions on fixed-array types (`extension [Int; 8]`)
            # are not supported. The builtin members `.len()` and `.swap(i, j)`
            # are the whole array surface; user methods on arrays are out of scope.
            self.error("extension methods on array types are not supported; "
                       "fixed arrays have the builtin `.len()` and `.swap(i, j)` only")
        else:
            self.error("Expected type name after 'extension'")

        # Parse optional type parameters or type arguments: <T, U> or <String, Int>
        # We parse as type_params first (existing behavior), but also try to parse as types.
        # The typechecker will determine which interpretation is correct based on namespace lookup.
        type_params = []
        type_args = []

        if self.match(TokenType.LT):
            # Try to parse - could be type params (T, U) or type args (String, Int)
            # We use a hybrid approach: parse with bounds support for type params
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
        while not self.match(TokenType.RBRACE, TokenType.EOF):
            member_doc = self._take_doc()
            if self.at_type_alias_start():
                # Parse type assignment: type Item = Int
                type_assign = self.parse_type_assignment()
                type_assignments.append(type_assign)
                if member_doc is not None:
                    # Type assignments carry no doc slot; report rather than drop.
                    self._release_doc(member_doc)
            elif self.match(TokenType.PUBLIC, TokenType.FUNC, TokenType.INIT,
                            TokenType.UNSAFE, TokenType.STATIC):
                # A member head, in the one order it is written:
                # `public static func ...`. Member visibility (design 80) comes
                # first; `static` (design 236) marks a static METHOD, and is the
                # same keyword design 149's module-level `static` variables use
                # in a different position — the member head only ever continues
                # into `func`, so the two never meet. A prefix `unsafe` on a
                # method or an `init` is design 136's old spelling and reaches
                # here only to be reported against the effect slot.
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
                # Attributes (design 58) are only legal on top-level func/static.
                self.error("attributes are not supported on methods")
            else:
                self.error(f"Expected 'type', 'func', or 'init' in extension, got {self.current().type.name}")
            self.skip_newlines()

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
        """Parse a module-level static declaration (design 41 + 149):

            static NAME: Type = initializer
            static NAME: Type                   (bare zero-init)
            unsafe static var NAME: Type = init (mutable — design 149 unit a)

        The initializer is optional to support bare zero-init for POD and
        fixed-array statics (slab regions need large zero arrays); the
        typechecker enforces the const-init, Sync-only and destructibility
        constraints.

        `var` and `unsafe` come as a pair. A mutable static is only ever
        `unsafe static var`: the consistency of compound global state comes from
        a serialization argument the compiler cannot see, and the `unsafe`
        declaration is what forces every touching function to state that it owns
        one. So each half without the other is a clean error naming the
        spelling, rather than a second, quieter way to declare global mutable
        state.
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
        while not self.match(TokenType.RBRACE, TokenType.EOF):
            functions.append(self.parse_extern_function())
            self.skip_newlines()

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
        # `extern blocking func` (design 18/22): an unbounded FFI call, treated
        # as a suspension source. `blocking` is a soft keyword valid only here.
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
            column=start.column
        )

    def _parse_static_modifier(self) -> bool:
        """Consume a member-head `static`, if present (design 236).

        `static` is the design-149 keyword in a new position. The two never
        collide because a DECLARATION head continues into a name and a colon
        (`static PAGE_SIZE: Int = 4096`) while a MEMBER head continues into
        `func` — and only an extension or a trait body reaches this at all.
        """
        if self.match(TokenType.STATIC):
            self.advance()
            return True
        return False

    def _check_static_declaration(self, name: str, declared_static: bool,
                                  has_receiver: bool, is_init: bool,
                                  kind: str, anchor) -> None:
        """design 236: the `static` keyword and the receiver must AGREE.

        Staticness WAS fully determined by the missing receiver, so inference
        doctrine permitted reading it off the parameter list — but
        reader-visibility trumps, and the V39 incident showed the inference
        silently converting an authoring MISTAKE into a different kind of
        method: a conformance row wrote `func dup(x: T)` meaning an instance
        method, forgot the `&self`, and got a static. The keyword turns
        forgot-`&self` into the right error at the right place.

        ENTRY POINTS — the only two places a method-shaped declaration is
        parsed, which is what makes this the rule's one chokepoint:
          * `parse_method`       — every extension member: struct AND enum
                                   (design 145 gives enums statics on the same
                                   terms), generic or not, at every visibility,
                                   `init` included so it can be refused.
          * `parse_trait_method` — every trait requirement, with or without a
                                   default body.
        Module-level `func`s are NOT methods and never reach here; neither does
        a compiler-SYNTHESIZED Method (a trait default's per-conformer copy, a
        derived `copy`/`equals`/`hash`, the place transform's window form),
        which is not authored source and carries the derived bit alone.
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
        consumed (design 236).
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
                # Subscript (design 141): `func [](&self, i: Int) borrows -> T`.
                # The method's name IS the string "[]", which is only reachable
                # through `v[i]` sugar — the symbol tables key methods by a
                # plain string and never validated identifier shape, so nothing
                # below this line needs to know.
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
            # Method-level generic type parameters (brief 36): `func map<U>(...)`.
            # These are IN ADDITION to the extension's own type params (the `T` in
            # `extension Vector<T>`); a call supplies them explicitly
            # (`v.map<Int>(...)`), inference is future work. `init` methods do not
            # take their own type params (they construct the extension's type).
            type_params = self.parse_type_params()
        else:
            self.error("Expected 'func' or 'init' in extension")

        self.expect(TokenType.LPAREN)
        parameters, self_mutable, self_is_reference, is_static = self.parse_method_parameters()
        self.expect(TokenType.RPAREN)

        self._check_static_declaration(
            name, declared_static, has_receiver=not is_static,
            is_init=is_init, kind="method", anchor=start)

        # Post-parameter effect slot (designs 18/22, design 24 item 3, design
        # 136): an extension method or `init` may be
        # `func name(...) unsafe sync [-> T]`. `sync` makes the body a checked
        # suspension-free context (`Method.is_sync`, honored by the effect
        # graph); `unsafe` declares contact with an unsafe type; `borrows`
        # (design 141) yields a place of the return type for a window.
        is_unsafe, is_sync, is_borrows = self._parse_effect_slot()
        if is_borrows and is_init:
            self.error(
                "`init` may not be `borrows` — an initializer CONSTRUCTS a "
                "value, and there is no prior storage for it to lend")
        if name == "[]" and not is_borrows:
            self.error(
                "a `[]` subscript must be `borrows` — `v[i]` names a PLACE in "
                "the container, not a value read out of it. Write "
                "`func [](&self, ...) borrows -> T`; a value-returning lookup "
                "is an ordinary named method")

        # Return type (optional, defaults to void)
        return_type = self.parse_return_clause(
            "`init`" if is_init else f"method `{name}`")

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
                # `var self` was an undocumented receiver spelling quietly
                # accepted as `&var self` (design 128 rider). The spec has two
                # receivers, both borrows, and the sigil is what says so — a
                # bare `var self` reads like a by-value consuming receiver,
                # which is not what it ever meant.
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

            # Trailing comma (design 129): the wrapping style this rule serves
            # puts one parameter per line, so `f(\n  a: Int,\n)` is accepted.
            if self.match(TokenType.RPAREN):
                break

            # Check for variadic marker (...) - stop parsing parameters
            if self.match(TokenType.ELLIPSIS):
                break

        return params, self_mutable, self_is_reference

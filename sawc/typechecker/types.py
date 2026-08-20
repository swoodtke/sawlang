"""
Type utility methods for the Saw type checker.

This module provides mixin methods for type resolution, compatibility checking,
and resource management trait detection (NoCopy, Copy, Deinit).

Usage:
    class TypeChecker(TypeUtilsMixin, ...):
        pass
"""

from contextlib import contextmanager
from typing import Optional, Tuple
from ast_nodes import (
    SawType, TypeKind, Visibility,
    Expression, Identifier, MoveExpr, ReferenceExpr, IntLiteral, Block,
    MemberAccess, ArrayIndex, TupleIndex, SelfExpr, ClosureExpr,
    BindOptional, OptionalEvalExpr, ForceUnwrap, MethodCall
)
from ast_walk import child_nodes
from errors import ErrorKind
from noescape import first_reference_in
from namespace import (
    SymbolKind, StructSymbol, EnumSymbol, FunctionSymbol, TraitSymbol, TypeAliasSymbol
)


class TypeUtilsMixin:
    """Mixin providing type utility methods for TypeChecker.

    Methods:
        get_struct_info: Lookup struct info via namespace
        get_enum_info: Lookup enum info via namespace
        get_function_info: Lookup function info via namespace
        get_trait_info: Lookup trait info via namespace
        _resolve_type_alias: Resolve type aliases in a SawType
        _resolve_type: Resolve user-defined types (enums parsed as structs)
        _get_underlying_type: Get underlying primitive type for distinct types
        _types_compatible: Check if two types are compatible
        _is_no_copy_type: Check if type implements NoCopy
        _is_implicit_copy_type: Check if type implements Copy
        _is_deinit_type: Check if type implements Deinit
        _check_no_copy_return: Validate NoCopy types are moved when returned
        _check_integer_literal_range: Validate integer literal fits target type
        _check_no_copy_containment: Check structs with NoCopy fields implement NoCopy
        _check_implicit_copy_containment: Check structs with Copy fields implement Copy
        _check_deinit_containment: Check structs with Deinit fields implement Deinit
    """

    # =========================================================================
    # Namespace Lookup Helpers
    # =========================================================================

    def _canonical_type_name(self, name: str, module=None) -> str:
        """`name` as the module-qualified type IDENTITY it denotes here.

        Total (design 144): a name that denotes no type — a type parameter, a
        forward reference, an already-canonical identity — comes back
        unchanged, so callers canonicalize unconditionally.

        "Here" is `_type_lookup_module()` unless a caller names the module
        (design 204): a std file's private type names are that file's, so the
        answer depends on who is asking."""
        ns = getattr(self, 'namespace', None)
        if ns is None or not name or '.' in name:
            return name
        if module is None:
            module = self._type_lookup_module()
        return ns.resolve_type_identity(name, module)

    def _canonical_trait_name(self, name: str) -> str:
        """A trait REFERENCE as its identity, resolving a module qualifier.

        DF-150b: a type-parameter bound and a trait's parent list hold bare
        STRINGS, not `SawType`s, so `_resolve_type`'s module-walk never sees
        them — `_canonical_type_name` deliberately leaves any dotted name alone
        for that branch to handle. A qualified `T: qual.Named` therefore stayed
        a literal spelling, matching no conformance registered under the trait's
        identity. Design 150 makes the qualifier the only way to name a trait a
        whole-module import brought in, so the string form has to resolve too.

        Total, like its sibling: an unresolvable name comes back unchanged and
        the existing "unknown trait" diagnostic reports it."""
        if not name or '.' not in name:
            return self._canonical_type_name(name)
        simple = name.rpartition('.')[2]
        trait = self.get_trait_info(simple, qualified_path=name)
        if trait is None:
            return name
        return getattr(trait, 'type_identity', "") or simple

    # Fields that hold a BACK-REFERENCE out of the tree being walked (a resolved
    # symbol, a declaring node). Following one would carry the walk below into
    # another module's declarations and rewrite them against THIS module's
    # name bindings — the one way a canonicalization pass can corrupt identity.
    _CANON_SKIP_FIELDS = frozenset((
        "symbol", "ast_node", "decl_node", "enum_symbol", "struct_symbol",
        "resolved_symbol", "target_symbol",
    ))

    def _stamp_annotation_kind(self, written, here, type_params=()) -> None:
        """Correct a written annotation's KIND in place, in the DECLARING
        module's own view (DF-212b).

        The parser defaults every bare capitalized name to `TypeKind.STRUCT` —
        it cannot know what the name denotes — and the three DECLARATION slots
        design 194 lists (a struct FIELD's type, an enum PAYLOAD's type, a
        `type R = T` right-hand side) are stored RAW and read straight off the
        AST, so nothing ever corrects that default for them. A field typed by
        an ENUM therefore sits in `StructSymbol.fields` as a STRUCT-kinded
        `SawType` with no symbol, and every consumer that compares it against a
        real value has to bridge the kinds by ASKING A NAMESPACE whether the
        name is an enum (`_types_compatible`'s generic-enum arm,
        `Namespace._normalize_struct_enum`). That question has a different
        answer in a different module, which is the whole of DF-212b: design
        84's cross-module embed splices a provider's suspending body into the
        ENTRY module's AST, the re-check compares the same field annotation
        there, the entry namespace reaches the provider's enum only DEEP (its
        shallow `has_enum` says no), so the bridge does not fire and a
        `Cmd`-typed field rejects a `Cmd` value — the same name printed twice.

        Stamping the kind HERE, where the declaration's own module view is in
        force, is design 210's rule applied one level down: the spliced subtree
        must carry fully-resolved identities BEFORE it lands, so no consumer
        downstream of the splice needs a namespace to finish the job. Nothing
        re-derives; the re-check consults the stamp.

        In place and conservative. In place because the symbol tables share
        these `SawType` OBJECTS with the AST (see `_canonicalize_module_types`),
        so one mutation updates every holder — which is what reaches
        `StructSymbol.fields` without enumerating the holders. Conservative
        because a name that resolves to a struct or a type alias, or to nothing
        at all (a type PARAMETER, a forward reference this module cannot see),
        is left exactly as it was: this only ever REPLACES a parser default
        with the answer the declaring module already has.

        Idempotent — an already-ENUM annotation never enters this arm — which
        matters because the front half re-enters the same AST (the place
        lowering and the coroutine transform both do).

        `type_params` is the set of TYPE-PARAMETER names in scope at this
        annotation, and it is load-bearing rather than defensive. A parameter
        may be spelled like a type this module declares — `struct Holder<Cmd>
        { v: Cmd }` beside an `enum Cmd` — and the field's `Cmd` is then the
        PARAMETER, not the enum. `SawType.substitute` matches a parameter
        reference through the STRUCT arm (`if self.struct_name in type_map`)
        and has no such arm for ENUM, since an enum name is nominal; flipping
        the kind would make monomorphization silently skip the field and
        `Holder<Int>` would carry an enum-typed one. Probed: without this the
        program above stops compiling.

        ENTRY POINT (obligation 1): `_canonicalize_module_types` only, which is
        itself reached from `check_program` (single-file + the builtins) and
        `check_module` (per module). One walk, one context, one answer.
        """
        name = written.struct_name
        if not name or '.' in name or name in type_params:
            return
        ns = getattr(self, 'namespace', None)
        if ns is None:
            return
        # A struct or an alias of this identity wins: only a name that is
        # UNAMBIGUOUSLY an enum here is a parser default worth correcting.
        if (ns.lookup_struct(name, here) is not None
                or ns.lookup_type_alias(name, here) is not None):
            return
        enum_symbol = ns.lookup_enum(name, here)
        if enum_symbol is None:
            return
        written.kind = TypeKind.ENUM
        written.enum_name = name
        written.struct_name = None
        written.symbol = enum_symbol

    def _canonicalize_module_types(self, module_ast) -> None:
        """Rewrite every type REFERENCE in `module_ast` to its identity, in place.

        Design 144's central invariant is that a resolved type reference carries
        its identity, so codegen never re-resolves a name against a merged
        namespace where two `Header`s live. Annotations are the half that
        `_resolve_type` cannot reach on its own: a struct FIELD type, a method
        signature and a `let x: T` are read straight off the AST by the checks
        and by codegen, many without ever passing through resolution.

        Since DF-212b the walk stamps the annotation's KIND as well as its
        name — see `_stamp_annotation_kind`. Same reason, one level down: an
        identity the declaring module resolved is one nobody downstream of a
        cross-module splice has to re-derive.

        In place, and by identity of the `SawType` OBJECT, because the symbol
        tables share those objects with the AST — `StructSymbol.fields` holds
        the very `SawType`s `struct.fields[i].type` does. Rewriting the object
        updates every holder at once, which is what makes the invariant hold
        without enumerating the holders.

        Runs per module, after that module's own types are registered (so its
        `type_names` view is complete) and before anything reads a signature.
        Idempotent: `resolve_type_identity` maps an identity to itself.

        PER FILE, not per module (design 204). The builtins are ONE AST built
        from thirty files, each its own module, and a std file's private type
        names are visible only inside it — so the walk carries the module of
        the source file it is inside, taken from a declaration's `source_file`
        and, more precisely, from a written type's own `written_file` (the
        provenance design 194 stamped). Outside std every file of a module
        answers the same, so this is inert for user code.
        """
        import dataclasses
        from ast_nodes import SawType as _SawType

        seen = set()

        def visit(obj, mod=None, tparams=frozenset()):
            if obj is None or isinstance(obj, (str, int, float, bool)):
                return
            key = id(obj)
            if key in seen:
                return
            if isinstance(obj, _SawType):
                seen.add(key)
                here = (self._vis_module_for_source(obj.written_file)
                        if obj.written_file else mod)
                if obj.struct_name:
                    obj.struct_name = self._canonical_type_name(
                        obj.struct_name, here)
                    # DF-212b: the identity is settled, so settle the KIND too,
                    # while this module's view is the one in force. `tparams`
                    # keeps a parameter spelled like one of this module's types
                    # out of it — that name is the PARAMETER.
                    self._stamp_annotation_kind(obj, here, tparams)
                if obj.enum_name:
                    obj.enum_name = self._canonical_type_name(
                        obj.enum_name, here)
                if obj.existential_trait:
                    obj.existential_trait = self._canonical_type_name(
                        obj.existential_trait, here)
                for child in (obj.element_types, obj.inner_type, obj.type_args,
                              obj.array_element_type, obj.param_types,
                              obj.func_return_type):
                    visit(child, mod, tparams)
                return
            if isinstance(obj, (list, tuple, set)):
                for item in obj:
                    visit(item, mod, tparams)
                return
            if isinstance(obj, dict):
                for item in obj.values():
                    visit(item, mod, tparams)
                return
            if dataclasses.is_dataclass(obj):
                seen.add(key)
                own_file = getattr(obj, 'source_file', None)
                if own_file:
                    mod = self._vis_module_for_source(own_file)
                # DF-212b: a generic declaration's parameters are in scope for
                # everything under it, and they NEST (a generic method inside a
                # generic extension). Accumulated on the way down so the kind
                # stamp never mistakes `Cmd` in `struct Holder<Cmd>` for the
                # module's `enum Cmd`.
                own_params = getattr(obj, 'type_params', None)
                if own_params:
                    names = {tp.name for tp in own_params
                             if getattr(tp, 'name', None)}
                    if names:
                        tparams = tparams | names
                # A TRAIT reference spelled as a bare string, not a `SawType`:
                # a type-parameter bound (`<T: Seed>`), a trait's parents, a
                # declared conformance list. A trait carries an identity like
                # any other type, and a bound that kept the spelling would stop
                # matching the conformance the extension registered under the
                # identity.
                for _slot in ("bounds", "parent_traits", "conformances"):
                    names = getattr(obj, _slot, None)
                    if isinstance(names, list) and all(
                            isinstance(n, str) for n in names):
                        # DF-150b: a bound or parent may be module-qualified;
                        # `conformances` keeps the spelling, which the orphan-rule
                        # check in registration resolves itself.
                        if _slot == "conformances":
                            setattr(obj, _slot,
                                    [self._canonical_type_name(n, mod)
                                     for n in names])
                        else:
                            with self._declaring(obj):
                                setattr(obj, _slot,
                                        [self._canonical_trait_name(n)
                                         for n in names])
                for f in dataclasses.fields(obj):
                    if f.name in self._CANON_SKIP_FIELDS:
                        continue
                    visit(getattr(obj, f.name, None), mod, tparams)
                return

        visit(module_ast)
        # A type alias resolved BEFORE this module's structs were registered
        # (aliases are registered first) can hold a rebuilt `SawType` that is
        # not in the AST, so it needs the walk explicitly.
        for type_def in getattr(module_ast, 'type_definitions', []):
            with self._declaring(type_def):
                alias = self.namespace.lookup_type_alias(
                    self._canonical_type_name(type_def.name))
            if alias is not None:
                mod = self._vis_module_for_source(
                    getattr(type_def, 'source_file', None))
                visit(alias.aliased_type, mod)
                visit(alias.immediate_type, mod)

    @staticmethod
    def _type_key(t) -> str:
        """A structural key for `t` that PRESERVES its identity (design 144).

        `str(t)` renders the SHORT name — that is what a human reads — so two
        same-named types from two modules print alike, and any comparison over
        that string would call them equal. The mangler's encoding is injective
        and carries the qualified name, so it is the right thing to compare."""
        from codegen.mangle import mangle_type
        try:
            return mangle_type(t)
        except Exception:
            return str(t)

    @staticmethod
    def _sym_identity(symbol, fallback: str) -> str:
        """The design-144 identity carried by a resolved type symbol.

        Every `SawType` built from a symbol goes through here: the symbol IS
        the resolution, so taking the name off the source spelling instead
        would throw that resolution away and make codegen guess."""
        return getattr(symbol, 'type_identity', "") or fallback

    def _report_type_ambiguity(self, category: str, name: str) -> bool:
        """Report a bare reference to a name two modules bind (design 144).

        With real identities two same-named public types coexist, so the merge
        no longer refuses the program — but a BARE use still cannot pick one.
        That is the design-142 use-site error, raised here once per name, with
        the wording and hint the merge-time diagnostic used."""
        ns = getattr(self, 'namespace', None)
        entry = ns.ambiguous_types.get(name) if ns is not None else None
        if entry is None:
            return False
        reported = getattr(self, '_reported_xmod_ambiguities', None)
        if reported is None:
            reported = set()
            self._reported_xmod_ambiguities = reported
        key = (category, name)
        if key in reported:
            return True
        reported.add(key)
        _cat, src1, src2 = entry
        self.reporter.error(
            ErrorKind.UNKNOWN_TYPE,
            f"ambiguous {_cat or category} `{name}`: defined in both "
            f"`{src1}` and `{src2}`",
            1, 1,
            hint=f"qualify the use (e.g. `{src1}.{name}`), or import "
                 f"`{name}` from a single module",
        )
        return True

    def get_struct_info(self, name: str, qualified_path: str = None, from_type: 'SawType' = None) -> Optional[StructSymbol]:
        """Lookup struct info via namespace, supporting qualified names.

        Args:
            name: Simple struct name (e.g., "Point")
            qualified_path: Optional module-qualified path (e.g., "toml.TomlDoc")
            from_type: Optional SawType that may contain a direct symbol reference

        Returns:
            StructSymbol if found, None otherwise
        """
        # First check if the type has a direct symbol reference (for module-qualified types)
        if from_type is not None:
            symbol = getattr(from_type, 'symbol', None)
            if symbol and symbol.kind == SymbolKind.STRUCT:
                return symbol
        if qualified_path:
            # Module-qualified lookup: "toml.TomlDoc"
            symbol = self.namespace.resolve(qualified_path, check_access=False)
            if symbol and symbol.kind == SymbolKind.STRUCT:
                return symbol
        # Local lookup (design 204: through the asking module's own view first)
        result = self.namespace.lookup_struct(name, self._type_lookup_module())
        if result:
            self._report_type_ambiguity('struct', name)
            return result
        # Search imported modules (for types that lost symbol during
        # substitution). Design 40 item 1 (L3): honor visibility — a private
        # struct of another module is not a candidate — and flag a name
        # exported by two different modules as an ambiguity instead of
        # resolving it silently by dict order.
        return self._cross_module_lookup('struct', name,
                                         lambda ns: ns.lookup_struct(name))

    def get_enum_info(self, name: str, qualified_path: str = None, from_type: 'SawType' = None) -> Optional[EnumSymbol]:
        """Lookup enum info via namespace, supporting qualified names.

        Args:
            name: Simple enum name (e.g., "Color")
            qualified_path: Optional module-qualified path (e.g., "colors.Color")
            from_type: Optional SawType that may contain a direct symbol reference

        Returns:
            EnumSymbol if found, None otherwise
        """
        # First check if the type has a direct symbol reference (for module-qualified types)
        if from_type is not None:
            symbol = getattr(from_type, 'symbol', None)
            if symbol and symbol.kind == SymbolKind.ENUM:
                return symbol
        if qualified_path:
            symbol = self.namespace.resolve(qualified_path, check_access=False)
            if symbol and symbol.kind == SymbolKind.ENUM:
                return symbol
        # Local lookup (design 204: through the asking module's own view first)
        result = self.namespace.lookup_enum(name, self._type_lookup_module())
        if result:
            self._report_type_ambiguity('enum', name)
            return result
        # Search imported modules (for types that lost symbol during
        # substitution). Design 40 item 1 (L3): visibility-honoring,
        # ambiguity-detecting fallback — see get_struct_info.
        return self._cross_module_lookup('enum', name,
                                         lambda ns: ns.lookup_enum(name))

    def _cross_module_lookup(self, category, name, lookup):
        """Visibility-honoring cross-module fallback for a bare type name.

        Scans imported module namespaces for `name`, keeping only symbols
        that are not PRIVATE (a private symbol of another module is invisible
        to the importer). Distinct definitions in two different modules are an
        unresolvable ambiguity — the bare use cannot pick one — so we report
        it (mirroring the merge-time collision diagnostic of design 26)
        instead of resolving by dict order. Builtins, which every module
        namespace shares by reference, dedup by object identity so re-seeing
        the same symbol object across modules is not a collision.
        """
        matches = []  # list of (module_name, symbol)
        for module_name, module_sym in self.namespace.modules.items():
            if not module_sym.namespace:
                continue
            # design 229: a module hands on its own surface. A name it merely
            # imports is not found through it, bare any more than qualified.
            if module_sym.namespace.hidden_import(name):
                continue
            sym = lookup(module_sym.namespace)
            if sym is None or getattr(sym, 'visibility', None) == Visibility.PRIVATE:
                continue
            # Dedup shared objects (builtins) by identity.
            if any(sym is existing for _, existing in matches):
                continue
            matches.append((module_name, sym))
        if not matches:
            return None
        if len(matches) >= 2:
            reported = getattr(self, '_reported_xmod_ambiguities', None)
            if reported is None:
                reported = set()
                self._reported_xmod_ambiguities = reported
            key = (category, name)
            if key not in reported:
                reported.add(key)
                src1, src2 = matches[0][0], matches[1][0]
                self.reporter.error(
                    ErrorKind.UNKNOWN_TYPE,
                    f"ambiguous {category} `{name}`: defined in both "
                    f"`{src1}` and `{src2}`",
                    1, 1,
                    hint=f"qualify the use (e.g. `{src1}.{name}`), or import "
                         f"`{name}` from a single module",
                )
        return matches[0][1]

    def get_function_info(self, name: str, qualified_path: str = None) -> Optional[FunctionSymbol]:
        """Lookup function info via namespace, supporting qualified names.

        Args:
            name: Simple function name (e.g., "main")
            qualified_path: Optional module-qualified path (e.g., "utils.helper")

        Returns:
            FunctionSymbol if found, None otherwise
        """
        if qualified_path:
            symbol = self.namespace.resolve(qualified_path, check_access=False)
            if symbol and symbol.kind == SymbolKind.FUNCTION:
                return symbol
        return self.namespace.lookup_function(name)

    def get_trait_info(self, name: str, qualified_path: str = None) -> Optional[TraitSymbol]:
        """Lookup trait info via namespace, supporting qualified names.

        Args:
            name: Simple trait name (e.g., "Iterator")
            qualified_path: Optional module-qualified path (e.g., "traits.Iterator")

        Returns:
            TraitSymbol if found, None otherwise
        """
        if qualified_path:
            symbol = self.namespace.resolve(qualified_path, check_access=False)
            if symbol and symbol.kind == SymbolKind.TRAIT:
                return symbol
        result = self.namespace.lookup_trait(name, self._type_lookup_module())
        if result is not None:
            return result
        # DF-150b: the same visibility-honoring cross-module fallback
        # `get_struct_info`/`get_enum_info` have had since design 40. A trait
        # reached through a module qualifier resolves to its own identity (see
        # `_resolve_type`'s EXISTENTIAL branch), and from then on every consumer
        # asks for it by that bare name — which is not in the importer's
        # namespace, because a whole-module import binds a qualifier and nothing
        # else. Without this, `&any qual.Named` type-checked its way to the
        # erasure site and then failed method dispatch with `unknown trait`.
        return self._cross_module_lookup('trait', name,
                                         lambda ns: ns.lookup_trait(name))

    def get_type_alias_info(self, name: str, qualified_path: str = None) -> Optional[TypeAliasSymbol]:
        """Lookup type alias info via namespace, supporting qualified names.

        Args:
            name: Simple type alias name (e.g., "MyInt")
            qualified_path: Optional module-qualified path

        Returns:
            TypeAliasSymbol if found, None otherwise
        """
        if qualified_path:
            symbol = self.namespace.resolve(qualified_path, check_access=False)
            if symbol and symbol.kind == SymbolKind.TYPE_ALIAS:
                return symbol
        local = self.namespace.lookup_type_alias(name, self._type_lookup_module())
        if local is not None:
            return local
        # An IMPORTED alias is still an alias. Without this the name resolves as
        # a type (an annotation using it checks fine) while every rule that asks
        # "is this an alias?" answers no — so the alias neither flows to its
        # underlying nor accepts its own constructor, and the failure appears one
        # module away from the declaration. `is_trivially_copyable` already
        # reached through imports this way; this makes the rest agree with it.
        return self.namespace._lookup_type_alias_deep(name)

    def get_method_info(self, struct_name: str, method_name: str,
                        spec_key: Tuple[str, ...] = None) -> Optional[FunctionSymbol]:
        """Lookup method info via namespace, supporting specialized methods.

        Args:
            struct_name: The struct name (e.g., "Point")
            method_name: The method name (e.g., "distance")
            spec_key: Optional tuple of type args for specialized methods

        Returns:
            FunctionSymbol if found, None otherwise
        """
        # First check specialized methods if a spec_key is provided
        if spec_key:
            specialized = self.namespace.lookup_specialized_method(struct_name, spec_key, method_name)
            if specialized:
                return specialized
        # Fall back to regular method lookup
        return self.namespace.lookup_method(struct_name, method_name)

    # =========================================================================
    # design 51: `any Trait` existential validation
    #
    # Two rules, both checked on DECLARED types (signatures, fields, bindings):
    #   1. Unsized discipline: `any Trait` is legal ONLY as the pointee of a
    #      reference (`&any Trait`) or the first type argument of `Box`
    #      (`Box<any Trait, A>`). Anywhere else it is rejected with a clean
    #      message — erased values live only behind explicit ownership.
    #   2. Object safety (v1): the trait must be dispatchable — not a marker
    #      (no methods), no associated types, and no method that takes/returns
    #      `Self` by value (the Copy family) or is generic. The `&var self`
    #      RECEIVER is always fine: it is not a `Self`-by-value parameter (the
    #      receiver slot is a VOID placeholder in `param_types`), so a mutating
    #      trait method is any-able (the future `Resumable` executor consumer).
    # =========================================================================

    # Compiler-known non-dispatchable marker traits: erasing them to `any` has
    # nothing to call. Send/Sync are structural markers; NoCopy is a pure marker
    # whose only resolved method is the inherited `deinit` (not a dispatch
    # surface); Copy/ExplicitCopy are Self-by-value anyway.
    _EXISTENTIAL_MARKER_TRAITS = {"Send", "Sync", "NoCopy"}

    def _validate_existential_type(self, t: Optional[SawType], line: int,
                                   column: int, slot_ok: bool = False):
        """Recursively enforce design 51's unsized discipline + object safety.

        `slot_ok` is True exactly at the two positions where an erased value is
        legal: the immediate pointee of a reference and `Box`'s first type arg.
        """
        if t is None:
            return
        kind = t.kind
        if kind == TypeKind.EXISTENTIAL:
            if not slot_ok:
                tn = t.existential_trait
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`any {tn}` is unsized and cannot be used by value here",
                    line, column,
                    hint=f"an erased value is legal only behind explicit "
                         f"ownership: `&any {tn}` (borrowed) or `Box<any {tn}>` "
                         f"(owned) — design 51")
                return
            self._check_object_safety(t.existential_trait, line, column)
            return
        if kind == TypeKind.REFERENCE:
            # Design 110 rider: a BARE trait name behind a reference
            # (`&var Shape` / `&Shape`) reaches here tagged STRUCT (the parser
            # cannot tell a trait from a struct). Left alone it would sail past
            # type checking and ICE in codegen ("Undefined struct: Shape").
            # Catch it as the same unsized-trait class as the `any`-placement
            # diagnostics, naming the fix (`&var any Shape`).
            inner = t.inner_type
            if (inner is not None and inner.kind == TypeKind.STRUCT
                    and inner.struct_name
                    and self.get_trait_info(inner.struct_name.split('.')[-1],
                                            qualified_path=inner.struct_name)
                    is not None):
                # Render the sigil exactly as `SawType.__repr__` does: `&T`
                # (no space) vs `&var T` (one space).
                sig = "&var " if t.reference_mutable else "&"
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`{sig}{inner.struct_name}` names a trait, which is unsized",
                    line, column,
                    hint=f"a trait can only be borrowed as an existential: write "
                         f"`{sig}any {inner.struct_name}`")
                return
            self._validate_existential_type(inner, line, column, slot_ok=True)
            return
        if kind == TypeKind.STRUCT:
            is_box = (t.struct_name == "Box")
            for i, a in enumerate(t.type_args or []):
                self._validate_existential_type(
                    a, line, column, slot_ok=(is_box and i == 0))
            return
        if kind == TypeKind.OPTIONAL:
            self._validate_existential_type(t.inner_type, line, column, slot_ok=False)
            return
        if kind == TypeKind.POINTER:
            self._validate_existential_type(t.inner_type, line, column, slot_ok=False)
            return
        if kind == TypeKind.ARRAY:
            self._validate_existential_type(
                t.array_element_type, line, column, slot_ok=False)
            return
        if kind == TypeKind.TUPLE:
            for e in (t.element_types or []):
                self._validate_existential_type(e, line, column, slot_ok=False)
            return
        if kind == TypeKind.ENUM:
            for a in (t.type_args or []):
                self._validate_existential_type(a, line, column, slot_ok=False)
            return
        if kind == TypeKind.FUNCTION:
            for p in (t.param_types or []):
                self._validate_existential_type(p, line, column, slot_ok=False)
            self._validate_existential_type(
                t.func_return_type, line, column, slot_ok=False)
            return

    def _check_object_safety(self, trait_name: str, line: int, column: int):
        """Diagnose why `any Trait` is (not) object-safe. Reported once per trait
        name to avoid duplicate diagnostics across many use sites."""
        reported = getattr(self, "_obj_safety_reported", None)
        if reported is None:
            reported = set()
            self._obj_safety_reported = reported

        simple = trait_name.split('.')[-1]
        trait = self.get_trait_info(simple, qualified_path=trait_name)
        if trait is None:
            trait = self.get_trait_info(simple)
        if trait is None:
            if trait_name not in reported:
                reported.add(trait_name)
                self._error(
                    ErrorKind.UNKNOWN_TYPE,
                    f"unknown trait `{trait_name}` in `any {trait_name}`",
                    line, column,
                    hint=self._retired_trait_hint(trait_name))
            return

        if trait.name in reported:
            return

        def fail(msg, hint=None):
            reported.add(trait.name)
            self._error(ErrorKind.TYPE_MISMATCH,
                        f"cannot form `any {trait_name}`: {msg}", line, column,
                        hint=hint)

        # design 186 fence (a), erasure half. Falls out of the marker rule
        # below, but a reader who wrote `any UnsafeSync` was reaching for a
        # thread-safety property and deserves to be told where it lives rather
        # than being told the trait has no methods.
        if trait.name in ("UnsafeSend", "UnsafeSync"):
            fail(f"`{trait.name}` is a declared assertion, not an erasable "
                 f"interface",
                 hint=f"`{trait.name}` appears in exactly one position, the "
                      f"conformance header. Neither `{trait.name}` nor "
                      f"`{trait.name[6:]}` can be erased — a marker trait has "
                      f"no methods to dispatch")
            return

        # Marker / non-dispatchable.
        if trait.name in self._EXISTENTIAL_MARKER_TRAITS or len(trait.methods) == 0:
            fail(f"`{trait.name}` is a marker trait with no methods to dispatch",
                 hint="only a trait with instance methods can be erased to `any`")
            return

        # Associated types (pinning `any T<Item = ...>` is deferred).
        if trait.associated_types:
            fail(f"`{trait.name}` has an associated type "
                 f"`{trait.associated_types[0]}` — `any` over a trait with "
                 f"associated types is not yet supported")
            return

        # Per-method safety: static requirements, Self-by-value params/returns,
        # generic methods.
        for mname, m in trait.methods.items():
            if getattr(m, "is_static", False):
                fail(f"method `{mname}` is static — it is called on the type, so "
                     f"there is no receiver to dispatch on",
                     hint="a trait with a static requirement is a generic bound "
                          "(`<T: " + trait.name + ">`), never an existential")
                return
            rt = m.return_type
            if rt is not None and self._names_self(rt):
                fail(f"method `{mname}` returns `Self` by value "
                     f"(Self-by-value signatures, including the Copy family, are "
                     f"not object-safe)")
                return
            # A `Self`-typed parameter is undispatchable BY REFERENCE exactly as
            # it is by value (design 239): two `any Trait` values need not share
            # a concrete type, so no vtable thunk can accept the operand either
            # way. The message names the parameter and its WRITTEN type — it
            # used to say "takes `Self` by value" about a `&Self` parameter,
            # which described neither the declaration nor the reason.
            _ptypes = list(m.param_types or [])
            _pnames = list(m.param_names or [])
            _off = len(_ptypes) - len(_pnames)
            for _i, pt in enumerate(_ptypes):
                if pt is None or not self._names_self(pt):
                    continue
                _j = _i - _off
                _named = (f"parameter `{_pnames[_j]}`"
                          if 0 <= _j < len(_pnames) else "a parameter")
                fail(f"method `{mname}` takes {_named} of type `{pt}` — a "
                     f"`Self`-typed parameter is not object-safe, by reference "
                     f"or by value")
                return
            if getattr(m, "type_params", None):
                fail(f"method `{mname}` is generic — generic methods are not "
                     f"object-safe")
                return

    def _names_self(self, t, depth=0):
        """Whether `t` NAMES `Self` anywhere, generic arguments included.

        `Result<Self, DecodeError>` is as unerasable as a bare `Self`: the vtable
        thunk would have to return a value whose size it does not know. Reading
        only the OUTER kind let a `-> Result<Self, E>` requirement through, which
        is how design 169's `Deserialize` first passed object safety.
        """
        if t is None or depth > 8:
            return False
        if t.kind == TypeKind.SELF:
            return True
        if t.inner_type is not None and self._names_self(t.inner_type, depth + 1):
            return True
        for arg in (t.type_args or []):
            if self._names_self(arg, depth + 1):
                return True
        return False

    def _validate_existentials_in_program(self, program):
        """Signature-level pass: validate every declared `any Trait` occurrence in
        struct fields, enum payloads, function/method signatures, and trait
        method signatures. Binding annotations are validated in the statement
        checker. Runs after trait registration so object safety can be judged."""
        for struct in getattr(program, 'structs', []):
            for field in struct.fields:
                self._validate_existential_type(
                    field.type, getattr(field, 'line', struct.line),
                    getattr(field, 'column', struct.column))
        for enum in getattr(program, 'enums', []):
            for variant in enum.variants:
                for payload in (variant.associated_types or []):
                    pt = payload[1] if isinstance(payload, tuple) else payload
                    self._validate_existential_type(pt, enum.line, enum.column)
        for func in getattr(program, 'functions', []):
            self._validate_function_signature_existentials(func)
        for ext in getattr(program, 'extensions', []):
            for method in ext.methods:
                self._validate_function_signature_existentials(method)
        for trait in getattr(program, 'traits', []):
            for tm in trait.methods:
                for p in tm.parameters:
                    self._validate_existential_type(
                        getattr(p, 'type', None), tm.line, tm.column)
                self._validate_existential_type(
                    tm.return_type, tm.line, tm.column)

    def _validate_function_signature_existentials(self, fn):
        line = getattr(fn, 'line', 0)
        column = getattr(fn, 'column', 0)
        for p in getattr(fn, 'parameters', []):
            self._validate_existential_type(getattr(p, 'type', None), line, column)
        self._validate_existential_type(
            getattr(fn, 'return_type', None), line, column)

    # --------------------------------------------------- design 188 (unit 1)
    # The no-escape walk, with type ALIASES RESOLVED (DF-188b).
    #
    # Design 163a/d refuse a reference wherever a declaration NAMES one — a
    # return type, a struct field, a generic argument, an enum payload. Every
    # one of those checks reads the type AS WRITTEN, in the parser, which is
    # where the position is known and where no alias can be resolved yet. So a
    # `type R = &Int` was a general bypass: the guarded positions see a plain
    # named type, and the alias's own back-conversion `R(&x)` inhabits it.
    #
    # This pass is the same walk over the same positions, run once the aliases
    # ARE known. It resolves at every step, so `Vector<R>`, `R?` and `[R; 4]`
    # are all caught, and it stops at a nested function TYPE exactly as the
    # written-form walk does — a function type's parameters take references
    # legitimately.

    def _alias_target(self, t):
        """What a named type ALIASES, or None when it names no alias — the
        resolver the shared no-escape walk takes."""
        if t.struct_name is None:
            return None
        alias = self.get_type_alias_info(t.struct_name)
        return alias.aliased_type if alias is not None else None

    def _first_laundered_reference(self, t, depth: int = 0):
        """The first reference reachable from `t` once aliases are resolved.

        The typechecker's entry to the one no-escape walk (`noescape.py`)."""
        return first_reference_in(t, self._alias_target, depth)

    def _reject_laundered_reference(self, t, what: str, line, column) -> None:
        """Report a reference at a declared position, aliases resolved.

        Reads for BOTH audiences, because three of the matrix's rows (a static,
        an associated-type assignment, a generic-parameter default) have no
        parser-side check at all and reach the user only here: a directly
        written `&T` gets the plain sentence, and a type that names one only
        after resolution gets the extra line saying an alias is not a way past
        the rule.
        """
        found = self._first_laundered_reference(t)
        if found is None:
            return
        value = found.inner_type if found.inner_type is not None else "T"
        if found is t:
            names_it = "is a reference"
        else:
            names_it = f"names a reference (`{found}`)"
        # Nothing in the WRITTEN type says `&`, so an alias is what hid it.
        via_alias = "" if "&" in str(t) else (
            ". A `type` alias is not a way past that rule: the walk resolves it")
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"{what} may not be a reference: `{t}` {names_it}, and references "
            f"in Saw are PARAMETERS ONLY — a reference borrows storage for the "
            f"duration of one call and may not escape it (designs 88/106)"
            f"{via_alias}",
            line, column,
            hint=f"use the value type (`{value}`), or — to hand out storage a "
                 f"type already owns — declare a `borrows` accessor "
                 f"(`... borrows -> {value}` with `lend`, design 141)")

    # THE POSITION MATRIX for the no-escape rule (design 193 unit 5 — the
    # process rule applied to its own worst offender). One row per place a
    # DECLARATION names a type that is not a parameter, each with the test that
    # covers it; `_no_escape_positions` yields exactly these rows, in order, and
    # nothing else.
    #
    # A PARAMETER is deliberately absent: that is where a reference belongs.
    # A LOCAL is absent too — a `let r = &x` is refused as an expression, by
    # the bare-`&` rule, not by a type walk. A closure's INFERRED return is not
    # a declared position and is checked at inference instead
    # (`_reject_reference_closure_return`, examples/errors/
    # ref_closure_return_inferred.saw).
    NO_ESCAPE_POSITIONS = (
        # row                            examples/errors/…
        ("struct field",                 "ref_field_type"),
        ("enum case payload",            "enum_ref_payload_escape"),
        ("function return",              "ref_return_dangles"),
        ("extension method return",      "ref_return_method"),
        ("trait method return",          "ref_return_trait_method"),
        ("extern function return",       "ref_return_extern"),
        ("static declaration",           "ref_static_declaration"),          # 193 u5
        ("associated-type assignment",   "ref_associated_type_assignment"),  # 193 u5
        ("generic-parameter default",    "ref_generic_param_default"),       # 193 u5
    )

    def _no_escape_positions(self, program):
        """Yield `(type, what, line, column)` for every position in
        `NO_ESCAPE_POSITIONS`, in that order."""
        for struct in getattr(program, 'structs', []):
            for field in struct.fields:
                yield (field.type, f"field `{field.name}` of `{struct.name}`",
                       getattr(field, 'line', struct.line),
                       getattr(field, 'column', struct.column))
        for enum in getattr(program, 'enums', []):
            for variant in enum.variants:
                for payload in (variant.associated_types or []):
                    name, pt = ((payload[0], payload[1])
                                if isinstance(payload, tuple)
                                else (variant.name, payload))
                    yield (pt,
                           f"payload `{name}` of case `{variant.name}` in enum "
                           f"`{enum.name}`", enum.line, enum.column)
        for func in getattr(program, 'functions', []):
            yield (getattr(func, 'return_type', None),
                   f"the return type of `{func.name}`",
                   getattr(func, 'line', 0), getattr(func, 'column', 0))
        for ext in getattr(program, 'extensions', []):
            for method in ext.methods:
                yield (getattr(method, 'return_type', None),
                       f"the return type of `{method.name}`",
                       getattr(method, 'line', ext.line),
                       getattr(method, 'column', ext.column))
        for trait in getattr(program, 'traits', []):
            for tm in trait.methods:
                yield (getattr(tm, 'return_type', None),
                       f"the return type of `{trait.name}.{tm.name}`",
                       getattr(tm, 'line', trait.line),
                       getattr(tm, 'column', trait.column))
        for block in getattr(program, 'extern_blocks', []):
            for fn in getattr(block, 'functions', []):
                yield (getattr(fn, 'return_type', None),
                       f"the return type of extern `{fn.name}`",
                       getattr(fn, 'line', 0), getattr(fn, 'column', 0))
        # A STATIC is storage that outlives the whole program — the longest-lived
        # position there is, and the one the matrix was missing.
        for static in getattr(program, 'statics', []):
            yield (getattr(static, 'type', None),
                   f"static `{static.name}`",
                   getattr(static, 'line', 0), getattr(static, 'column', 0))
        # An ASSOCIATED-TYPE assignment names the type every use of that
        # associated name resolves to — a field's type, a return type, a
        # generic argument — so a reference here reaches all of them at once.
        for ext in getattr(program, 'extensions', []):
            for assign in (getattr(ext, 'type_assignments', None) or []):
                yield (getattr(assign, 'assigned_type', None),
                       f"associated type `{assign.name}` of "
                       f"`{getattr(ext, 'struct_name', '?')}`",
                       getattr(assign, 'line', ext.line),
                       getattr(assign, 'column', ext.column))
        # A generic parameter's DEFAULT is substituted before mangling, so
        # `struct Holder<T = &Int>` writes `&Int` into every field typed `T`
        # without any use site naming it — the DF-163d shape by another route.
        for decl in self._declarations_with_type_params(program):
            for tp in (getattr(decl, 'type_params', None) or []):
                if getattr(tp, 'is_const', False):
                    continue
                yield (getattr(tp, 'default', None),
                       f"the default of type parameter `{tp.name}`",
                       getattr(tp, 'line', 0) or getattr(decl, 'line', 0),
                       getattr(tp, 'column', 0) or getattr(decl, 'column', 0))

    def _validate_no_ref_laundering_in_program(self, program):
        """Signature-level pass: no declared position NAMES a reference once
        aliases are resolved (DF-188b).

        Drives `_no_escape_positions` — see `NO_ESCAPE_POSITIONS` above for the
        matrix itself. Three of its rows are checked ONLY here (a static, an
        associated-type assignment and a generic-parameter default are not
        positions the parser's written-form walk ever visited), so this pass is
        the whole rule for them and the alias half for the rest.
        """
        for t, what, line, column in self._no_escape_positions(program):
            self._reject_laundered_reference(t, what, line, column)

    # ------------------------------------------------------- design 148 (unit A)

    # Bounds the compiler knows structurally. Every one of these is also declared
    # in `builtin.saw`, so `get_trait_info` normally finds it — but the structural
    # checkers (`namespace.type_satisfies_bound`) answer for them without a
    # `TraitSymbol`, and a profile that does not link `builtin.saw` still writes
    # them. Naming them here keeps the validator from rejecting a bound the rest
    # of the compiler happily enforces.
    _STRUCTURAL_BOUNDS = frozenset({
        "Copy", "Equatable", "Comparable", "Hashable", "Printable",
        "Send", "Sync",
    })

    # Const VALUE parameters are Int or UInt in v1 (design 148). Fixed-width
    # value parameters are a later question; nothing in the language needs one
    # yet, and admitting them now would fix an encoding in the mangling before
    # there is a use to judge it against.
    _CONST_PARAM_KINDS = (TypeKind.INT, TypeKind.UINT)

    def _resolve_const_params_in_program(self, program):
        """Check const VALUE parameters and materialize their defaults.

        Runs before anything reads a type parameter, because a default has to be
        a value by the time the first reference site omits it. A const default is
        a closed constant expression — it may not mention another parameter in
        v1 — so it needs no namespace and can be folded this early.

        The default becomes a `CONST_VALUE` `SawType` in the ordinary `default`
        slot, which is what lets a value default ride design 37's
        default-argument machinery with no changes: the fillers substitute
        whatever type is there.
        """
        for decl in self._declarations_with_type_params(program):
            for tp in (getattr(decl, 'type_params', None) or []):
                if getattr(tp, 'is_const', False):
                    self._resolve_const_param(tp, decl)

    @staticmethod
    def _declarations_with_type_params(program):
        for struct in getattr(program, 'structs', []):
            yield struct
        for enum in getattr(program, 'enums', []):
            yield enum
        for trait in getattr(program, 'traits', []):
            yield trait
        for func in getattr(program, 'functions', []):
            yield func
        for ext in getattr(program, 'extensions', []):
            yield ext
            for method in ext.methods:
                yield method

    def _resolve_const_param(self, tp, decl):
        line = getattr(tp, 'line', 0) or getattr(decl, 'line', 0)
        column = getattr(tp, 'column', 0) or getattr(decl, 'column', 0)

        vt = tp.const_type
        if vt is None or vt.kind not in self._CONST_PARAM_KINDS:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"a const parameter is `Int` or `UInt`, and `{tp.name}` is "
                f"declared `{vt}`",
                line, column,
                hint="const generics carry integer values in v1 — a parameter "
                     "of a user type is not supported")
            tp.const_type = SawType(TypeKind.INT)
            return

        if tp.const_default_expr is None or tp.default is not None:
            return
        from const_eval import const_eval, ConstEvalError
        try:
            value = const_eval(tp.const_default_expr,
                               width=self.platform_int_width)
        except ConstEvalError as e:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"the default for const parameter `{tp.name}` is not a "
                f"compile-time constant: {e.what} is not allowed here",
                e.line or line, e.column or column,
                hint="a const parameter's default is a closed constant — it "
                     "may not read another parameter")
            return
        if isinstance(value, bool) or not isinstance(value, int):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"the default for const parameter `{tp.name}` must be an "
                f"integer",
                line, column)
            return
        tp.default = SawType(TypeKind.CONST_VALUE, const_value=value,
                             inner_type=vt)

    def _validate_type_param_bounds_in_program(self, program):
        """Declaration-level pass: every type-parameter bound names a TRAIT.

        A bound is the one place in a generic declaration where an arbitrary
        identifier is accepted, and until design 148 nothing ever checked it. So
        `struct FixedBuf<N: Int>` compiled clean and then failed at every USE
        with "undefined variable `N`" / "undefined variable `FixedBuf`" — the
        diagnosis surfacing at the use site, in terms that name neither the
        declaration nor the real mistake (DF-137a). Checking it here turns a
        silent-wrong-answer into an error that points at the bound itself.

        Runs after trait registration for the same reason the existential pass
        does: structs and enums register BEFORE traits, so `_register_struct`
        cannot yet resolve a user trait, and a check inside it would reject
        every forward reference.
        """
        for struct in getattr(program, 'structs', []):
            self._validate_type_param_bounds(
                struct.type_params, struct.line, struct.column)
        for enum in getattr(program, 'enums', []):
            self._validate_type_param_bounds(
                enum.type_params, enum.line, enum.column)
        for trait in getattr(program, 'traits', []):
            self._validate_type_param_bounds(
                trait.type_params, trait.line, trait.column)
        for func in getattr(program, 'functions', []):
            self._validate_type_param_bounds(
                func.type_params, func.line, func.column)
        for ext in getattr(program, 'extensions', []):
            # An extension's `<...>` list doubles as a SPECIALIZATION
            # (`extension Vector<String>`), where the "parameter" is a concrete
            # type name carrying no bounds. Only a bounded entry is a real
            # parameter, and only those are checked.
            self._validate_type_param_bounds(
                ext.type_params, ext.line, ext.column)
            for method in ext.methods:
                self._validate_type_param_bounds(
                    getattr(method, 'type_params', None),
                    getattr(method, 'line', ext.line),
                    getattr(method, 'column', ext.column))

    def _validate_type_param_bounds(self, type_params, line, column):
        """Check one declaration's type-parameter list."""
        for tp in (type_params or []):
            tp_line = getattr(tp, 'line', 0) or line
            tp_column = getattr(tp, 'column', 0) or column
            for bound in (getattr(tp, 'bounds', None) or []):
                self._validate_one_bound(tp, bound, tp_line, tp_column)

    def _validate_one_bound(self, tp, bound, line, column):
        if bound in self._STRUCTURAL_BOUNDS:
            return
        # design 188 unit 4 fence: `NoMove` is a property of a CONCRETE type's
        # storage, not a capability a generic body can use. A bound exists to
        # let a body DO something with every instantiation; there is nothing a
        # `T: NoMove` body could do that an unbounded one cannot, and admitting
        # one would invite the projection/Pin machinery v1 deliberately has not
        # got.
        if bound.rsplit('.', 1)[-1] == "NoMove":
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`NoMove` is not a generic bound, so it cannot bound the type "
                f"parameter `{tp.name}`",
                line, column,
                hint="`NoMove` is declared at the CONFORMANCE position "
                     "(`extension T: NoMove {}`, beside the required "
                     "`extension T: NoCopy {}`) and says where a value may "
                     "live, not what a generic body may do with it")
            return
        # design 186 fence (a): the ASSERTION is not the property. `UnsafeSync`
        # and `UnsafeSend` appear in exactly one position — the conformance
        # header — because a generic body wants "this is safe to share", not
        # "somebody said so"; a `T: Sync` bound is satisfied BY a declared
        # `UnsafeSync` through the parent trait, so the vocabulary generic code
        # writes never has to name the assertion at all.
        if bound.rsplit('.', 1)[-1] in ("UnsafeSend", "UnsafeSync"):
            simple = bound.rsplit('.', 1)[-1]
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{simple}` is not a generic bound, so it cannot bound the "
                f"type parameter `{tp.name}`",
                line, column,
                hint=f"bound on the PROPERTY instead — `{tp.name}: "
                     f"{simple[6:]}` — which a type declaring `{simple}` "
                     f"satisfies through it. The assertion is written once, at "
                     f"the conformance header, where it can be audited")
            return
        simple = bound.split('.')[-1]
        if self.get_trait_info(simple, qualified_path=bound) is not None:
            return
        if self.get_trait_info(simple) is not None:
            return

        # `<N: Int>` is not a mistaken bound so much as a guess at const
        # generics, and it is the exact spelling DF-137a was filed over. Since
        # design 148 there is a real one to point at, so the fixit names it.
        if bound in ("Int", "UInt"):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{bound}` is a type, not a trait, so it cannot bound the "
                f"type parameter `{tp.name}`",
                line, column,
                hint=f"to take a compile-time VALUE, write "
                     f"`const {tp.name}: {bound}` — a bound names a trait the "
                     f"argument must conform to, not the value's type")
            return

        # The name resolves to something — just not a trait. Say which, so the
        # author is not left hunting for a missing `trait` declaration that was
        # never the problem.
        if self._is_known_type(simple):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{bound}` is a type, not a trait, so it cannot bound the "
                f"type parameter `{tp.name}`",
                line, column,
                hint="a type parameter's bound names a trait the argument must "
                     "conform to (`T: Printable`, `T: Copy + Equatable`)")
            return
        self._error(
            ErrorKind.UNDEFINED_VARIABLE,
            f"unknown trait `{bound}` in the bound on type parameter "
            f"`{tp.name}`",
            line, column,
            hint=self._retired_trait_hint(bound)
                 or "a type parameter's bound must name a trait that is in scope")

    # THE RETIRED TRAIT NAMES (design 219 unit B4) — one table, one helper.
    #
    # A name the language used to define and no longer does deserves better than
    # "unknown trait": the author wrote something that WAS correct, and the fix
    # is a word. Every unknown-trait diagnostic asks this first — the two type
    # parameter-bound sites in `expressions.py`, the bound site above, the `any
    # Trait` erasure site, the method-dispatch site, and the conformance-header
    # site in `registration.py` — so the hint cannot appear at some of the
    # positions a retired name can be written in and not the rest.
    _RETIRED_TRAIT_HINTS = {
        "ImplicitCopy": "`ImplicitCopy` was merged into `Copy` (design 219) — "
                        "write `Copy`",
    }

    def _retired_trait_hint(self, name):
        """The teaching hint for a trait name the language retired, or None.

        Callers: every `unknown trait` diagnostic. See the table above.
        """
        return self._RETIRED_TRAIT_HINTS.get((name or "").rsplit('.', 1)[-1])

    # ------------------------------------------------------- design 136 (unit B)

    def _validate_fn_effects_in_program(self, program):
        """Signature-level pass: every written function TYPE spells the `unsafe`
        effect its own signature carries, and no other (design 136).

        Runs over the same declared positions as the existential pass, and for
        the same reason: the rule needs struct registration (an `unsafe struct`
        is only known by then) and it judges the annotation AS WRITTEN. Judging
        the written form is also what keeps generics out of it — a `(T) sync ->
        R` slot is checked once, against the type parameter, not again against
        every instantiation that may substitute a pointer for `T`.
        """
        for struct in getattr(program, 'structs', []):
            src = getattr(struct, 'source_file', None)
            for field in struct.fields:
                self._validate_fn_type_effect(
                    field.type, getattr(field, 'line', struct.line),
                    getattr(field, 'column', struct.column), src)
        for enum in getattr(program, 'enums', []):
            for variant in enum.variants:
                for payload in (variant.associated_types or []):
                    pt = payload[1] if isinstance(payload, tuple) else payload
                    self._validate_fn_type_effect(
                        pt, enum.line, enum.column,
                        getattr(enum, 'source_file', None))
        for func in getattr(program, 'functions', []):
            self._validate_fn_effects_in_signature(func)
        for ext in getattr(program, 'extensions', []):
            for method in ext.methods:
                self._validate_fn_effects_in_signature(method)
        for trait in getattr(program, 'traits', []):
            for tm in trait.methods:
                self._validate_fn_effects_in_signature(
                    tm, source_file=getattr(trait, 'source_file', None))
        for static in getattr(program, 'statics', []):
            self._validate_fn_type_effect(
                getattr(static, 'type_annotation', None), static.line,
                static.column, getattr(static, 'source_file', None))

    def _validate_fn_effects_in_signature(self, fn, source_file=None):
        line = getattr(fn, 'line', 0)
        column = getattr(fn, 'column', 0)
        src = source_file or getattr(fn, 'source_file', None)
        for p in getattr(fn, 'parameters', []):
            self._validate_fn_type_effect(getattr(p, 'type', None), line,
                                          column, src)
        self._validate_fn_type_effect(getattr(fn, 'return_type', None), line,
                                      column, src)

    def _validate_fn_type_effect(self, t, line: int, column: int,
                                 source_file=None):
        """Check one written type annotation, and everything nested in it.

        A function type carries `unsafe` exactly when a parameter or its return
        names an unsafe type. Both halves are errors: the effect on an all-safe
        signature claims an obligation the types cannot express, and its absence
        on a signature that does name one hides the obligation from the reader
        while the compiler treats the type as unsafe anyway.
        """
        if t is None:
            return
        if t.kind == TypeKind.FUNCTION:
            names_unsafe = self._fn_signature_names_unsafe(t)
            if getattr(t, 'func_is_unsafe', False) and not names_unsafe:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"the function type `{t}` declares `unsafe` but its "
                    f"signature names no unsafe type",
                    line, column,
                    hint="a function taking only safe types must be sound for "
                         "every input; unsafety enters a signature only through "
                         "its types — drop the `unsafe`, or state the "
                         "precondition by taking a parameter of unsafe type",
                    source_file=source_file)
            elif names_unsafe and not getattr(t, 'func_is_unsafe', False):
                found = None
                for pt in (t.param_types or []):
                    found = self._first_unsafe_type(pt)
                    if found is not None:
                        break
                if found is None:
                    found = self._first_unsafe_type(t.func_return_type)
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"the function type `{t}` names an unsafe type "
                    f"(`{found}`) but its effect slot does not say `unsafe`",
                    line, column,
                    hint="write the effect the signature carries, e.g. "
                         "`(UnsafePointer<T>) unsafe sync -> R` — one contract "
                         "has one spelling",
                    source_file=source_file)
        for sub in (getattr(t, 'inner_type', None),
                    getattr(t, 'array_element_type', None),
                    getattr(t, 'func_return_type', None)):
            self._validate_fn_type_effect(sub, line, column, source_file)
        for group in ('type_args', 'element_types', 'param_types'):
            for sub in (getattr(t, group, None) or []):
                self._validate_fn_type_effect(sub, line, column, source_file)

    # =========================================================================
    # Type Resolution Methods
    # =========================================================================

    def _resolve_type_alias(self, saw_type: SawType) -> SawType:
        """Resolve any type aliases in a SawType."""
        if saw_type.kind == TypeKind.STRUCT:
            # Check if this is actually a type alias
            alias_sym = self.get_type_alias_info(saw_type.struct_name)
            if alias_sym:
                return alias_sym.aliased_type
            # Recursively resolve type_args
            if saw_type.type_args:
                resolved_args = [self._resolve_type_alias(t) for t in saw_type.type_args]
                return SawType(TypeKind.STRUCT, struct_name=saw_type.struct_name, type_args=resolved_args)
            return saw_type
        elif saw_type.kind == TypeKind.OPTIONAL:
            if saw_type.inner_type:
                resolved_inner = self._resolve_type_alias(saw_type.inner_type)
                return SawType(TypeKind.OPTIONAL, inner_type=resolved_inner)
            return saw_type
        elif saw_type.kind == TypeKind.TUPLE:
            if saw_type.element_types:
                resolved_elems = [self._resolve_type_alias(t) for t in saw_type.element_types]
                return SawType(TypeKind.TUPLE, element_types=resolved_elems,
                               tuple_field_names=saw_type.tuple_field_names)
            return saw_type
        elif saw_type.kind == TypeKind.ENUM:
            if saw_type.type_args:
                resolved_args = [self._resolve_type_alias(t) for t in saw_type.type_args]
                return SawType(TypeKind.ENUM, enum_name=saw_type.enum_name, type_args=resolved_args, symbol=saw_type.symbol)
            return saw_type
        else:
            return saw_type

    def _append_default_type_args(self, name: str, args, is_enum: bool = False):
        """Design 37 — canonical default-type-parameter fill.

        Given the type arguments written at a reference site for a named
        struct/enum, append the declared DEFAULTS for any omitted trailing type
        parameters, so `Vector<Int>` canonicalizes to `Vector<Int, Global>`
        BEFORE the type is ever used for identity/mangling. This is the single
        identity rule: because every resolution path funnels through here,
        `Vector<Int>` and `Vector<Int, Global>` collapse to one type, one
        mangled name, one monomorphized struct — they can never diverge.

        Total and non-diagnostic: if a missing trailing parameter has no default
        the arg list is left under-applied (the arity error is raised at the
        construction/annotation check, not here). Defaults referencing an
        earlier parameter are not supported — every default in the stdlib is a
        ground type (`Global`); such a default is resolved as written.
        """
        info = self.get_enum_info(name) if is_enum else self.get_struct_info(name)
        params = getattr(info, 'type_params', None) if info is not None else None
        if not params:
            return args
        # DF-172j: a bare NAME on a const parameter may be a module `static`.
        # The parser cannot tell `FixedBuf<CAP>`'s argument from a type, so it
        # arrives here as one; this is the same chokepoint the paragraph above
        # describes, and the same reason applies — the argument has to BE a
        # number before anything takes the type's identity from it.
        args = self._const_static_args(args, params)
        if len(args) >= len(params):
            return args
        filled = list(args)
        for i in range(len(args), len(params)):
            default = getattr(params[i], 'default', None)
            if default is None:
                break
            filled.append(self._resolve_type(default))
        return filled

    def _self_type_is_substitutable(self, self_type) -> bool:
        """Is this extension's `Self` a type that may be written into a
        signature (DF-216f)?

        No, exactly when the concrete type came back ARGUMENT-FREE for a
        parameterized type — `Wrap` for `extension Wrap<T>`. That spelling is
        deliberate (see `_ext_self_type`), and it is usable as a receiver
        because codegen resolves it through `self_type_context`; it is NOT
        usable as a written parameter or return type, where the missing
        arguments name a struct no monomorphization registered.

        DF-216r made this the BACKSTOP rather than the rule. Written positions
        are handed `_ext_written_self_type`'s answer, which applies the
        extension to its own parameters (`Wrap<T>`) and therefore passes here;
        what still reaches this guard is the case that helper deliberately
        declines — an extension whose parameters include a CONST one — plus any
        future caller that forgets which of the two `Self`s it wants.
        """
        if self_type is None:
            return False
        if self_type.kind == TypeKind.STRUCT and self_type.struct_name:
            info = self.get_struct_info(self_type.struct_name)
        elif self_type.kind == TypeKind.ENUM and self_type.enum_name:
            info = self.get_enum_info(self_type.enum_name)
        else:
            return True     # a primitive pseudo-struct has no parameters
        type_params = getattr(info, 'type_params', None) if info else None
        if not type_params:
            return True
        return bool(self_type.type_args)

    def _substitute_self_type(self, t, concrete, depth: int = 0):
        """Replace `Self` with the extension's concrete type ANYWHERE in `t`.

        THE ONE `Self` substitution (DF-216f). Every site that needed one used
        to test `t.kind == TypeKind.SELF` at the ROOT and nowhere else, so a
        bare `Self` resolved and a `Self` under any type constructor resolved
        nowhere. The filing read that as "parameters are broken, returns work";
        the real axis is TOP-LEVEL versus NESTED, and it cuts across both sides
        of the signature — `-> Self?` and `-> (Self, Int)` were broken exactly
        as `other: &Self` was.

        Entry points, all five, each of which had the root-only test:

          - an extension method's registered PARAMETER types and its RETURN type
            (`_register_extension`)
          - the same two on the body side, where the parameter becomes a binding
            and the return becomes the expected type (`_check_extension_method`)
          - a parameter DEFAULT's expected type (`_check_parameter_defaults`)

        Non-mutating, and it rebuilds through `dataclasses.replace` so every
        other field of the node — a reference's mutability, a tuple's field
        names, an array's length, a function type's effect bits — rides along
        untouched. A tree with no `Self` in it comes back as the SAME object, so
        this is free for the overwhelming majority of signatures.

        WHICH `Self` IS SUBSTITUTED IN is the caller's business, and on a
        GENERIC extension the two differ (DF-216r). `_ext_self_type` answers
        for the RECEIVER and is deliberately ARGUMENT-FREE there — `Wrap`, not
        `Wrap<T>` — because naming the extension's own parameters as arguments
        makes a payload binding and a `T` parameter resolve through different
        routes to two `T`s that do not unify; codegen names the concrete
        monomorphization from `self_type_context` instead. Substituting THAT
        into a signature would put a bare `Wrap` where only `Wrap$1$Int`
        exists, turning a clean type error into `Undefined struct: Wrap`. Every
        written position therefore passes `_ext_written_self_type`'s answer
        instead, and `_self_type_is_substitutable` below stays as the backstop
        for the one shape that helper declines (a const parameter).
        """
        if t is None or concrete is None or depth > 16:
            return t
        if depth == 0 and not self._self_type_is_substitutable(concrete):
            return t
        if t.kind == TypeKind.SELF:
            return concrete
        import dataclasses
        repl = {}
        for slot in ('inner_type', 'array_element_type', 'func_return_type'):
            cur = getattr(t, slot, None)
            if cur is None:
                continue
            new = self._substitute_self_type(cur, concrete, depth + 1)
            if new is not cur:
                repl[slot] = new
        for slot in ('type_args', 'element_types', 'param_types'):
            cur = getattr(t, slot, None)
            if not cur:
                continue
            new = [self._substitute_self_type(c, concrete, depth + 1)
                   for c in cur]
            if any(a is not b for a, b in zip(new, cur)):
                repl[slot] = new
        if not repl:
            return t
        return dataclasses.replace(t, **repl)

    def _resolve_qualified_symbol(self, dotted_name: str):
        """THE module-qualifier walk: `(symbol, identity)` for `mod.Type`, or None.

        ONE definition, two entry points — and the second is why it was worth
        extracting (DF-194a):

          - `_resolve_type`, which every EXPRESSION-position and signature-position
            annotation reaches, and
          - `_resolve_declared_qualified_names`, the walk over the three
            declaration slots stored RAW (a struct FIELD's type, an enum case
            PAYLOAD's type, a `type` alias right-hand side). Those never reach
            `_resolve_type` as a unit, so before this existed a qualified name
            written in one kept its dotted SPELLING into type comparison and
            `dep.Point` and `Point` were two types.

        The walk itself is design 229's: every hop past the first reaches THROUGH
        a module, so a qualifier that module merely IMPORTED is not a hop this
        spelling may take, and the name at the end is read off that module's own
        surface with `check_visibility=True`. Both entry points get that check
        because both come through here — which is the reason the declaration slots
        route to this rather than to a canonicalizing name rewrite.

        Total: an unresolvable qualifier answers None and the caller leaves the
        written spelling alone for the existing diagnostic to report.
        """
        parts = dotted_name.split('.')
        simple_name = parts[-1]
        module_parts = parts[:-1]

        current_ns = self.namespace
        through_import = False
        for part in module_parts:
            if through_import and current_ns.hidden_import(part, as_module=True):
                return None
            module_sym = current_ns.modules.get(part)
            if module_sym and module_sym.namespace:
                current_ns = module_sym.namespace
                through_import = True
            else:
                return None

        symbol = current_ns.resolve(
            simple_name, check_visibility=True,
            # DF-232j: the module of the CODE being checked, which the std-leaf
            # case makes different from the loaded namespace's path.
            accessor_module=self._accessor_vis_module(),
            through_import=through_import,
        )
        if not symbol:
            return None
        # Design 144: the resolved reference carries the target's IDENTITY, not
        # the spelling `mod.Type` was written with, so codegen never re-resolves
        # a name it was handed.
        identity = getattr(symbol, 'type_identity', "") or simple_name
        return symbol, identity

    def _resolve_declared_qualified_names(self, written, depth: int = 0):
        """Resolve MODULE-QUALIFIED names inside one of the three RAW declaration
        slots (DF-194a), returning the annotation to store.

        Entry points, and there are exactly three — the slots design 194 unit 4
        had to wire the prelude gate into by hand, for the same reason:

          - a struct FIELD's type (`_register_struct`)
          - an enum case PAYLOAD's type (`_register_enum`)
          - a `type` alias right-hand side (`_register_type_definition`)

        Each stores its annotation straight off the AST and reads it back
        unresolved, so `_resolve_type` — the one place that walks a qualifier —
        never runs on it. Design 150 promises a qualifier works in EVERY position
        a name appears; these were the three where it did not.

        NARROW on purpose: it rewrites a DOTTED name and nothing else. A bare name
        is left exactly as written, so the DF-212b kind stamp in
        `_canonicalize_module_types` (which knows the type PARAMETERS in scope and
        must, since `struct Holder<Cmd>` beside an `enum Cmd` means the parameter)
        still settles those, and the prelude gate still runs at the slot rather
        than twice. A dotted name can never be a type parameter, which is what
        makes this half safe to settle here and now.

        In place for CHILDREN (the symbol tables share these objects with the
        AST), and by return value for the node itself, whose resolution builds a
        new `SawType` carrying the target's identity and symbol.
        """
        if written is None or depth > 8:
            return written
        # Written out slot by slot rather than looped over names: a computed
        # `setattr` is invisible to the design-126 AST-contract gate, which can
        # only account for attributes it can see being assigned.
        if written.inner_type is not None:
            written.inner_type = self._resolve_declared_qualified_names(
                written.inner_type, depth + 1)
        if written.array_element_type is not None:
            written.array_element_type = self._resolve_declared_qualified_names(
                written.array_element_type, depth + 1)
        if written.func_return_type is not None:
            written.func_return_type = self._resolve_declared_qualified_names(
                written.func_return_type, depth + 1)
        if written.type_args:
            written.type_args = [
                self._resolve_declared_qualified_names(c, depth + 1)
                for c in written.type_args]
        if written.element_types:
            written.element_types = [
                self._resolve_declared_qualified_names(c, depth + 1)
                for c in written.element_types]
        if written.param_types:
            written.param_types = [
                self._resolve_declared_qualified_names(c, depth + 1)
                for c in written.param_types]
        name = None
        if written.kind == TypeKind.STRUCT and written.struct_name:
            name = written.struct_name
        elif written.kind == TypeKind.ENUM and written.enum_name:
            name = written.enum_name
        if not name or '.' not in name:
            return written
        found = self._resolve_qualified_symbol(name)
        if found is None:
            return written
        symbol, identity = found
        args = written.type_args or None
        if symbol.kind == SymbolKind.STRUCT:
            if args:
                args = self._append_default_type_args(identity, args)
            return SawType(TypeKind.STRUCT, struct_name=identity,
                           type_args=args, symbol=symbol)
        if symbol.kind == SymbolKind.ENUM:
            if args:
                args = self._append_default_type_args(identity, args,
                                                      is_enum=True)
            return SawType(TypeKind.ENUM, enum_name=identity,
                           type_args=args, symbol=symbol)
        return written

    def _resolve_type(self, saw_type: SawType) -> SawType:
        """Resolve user-defined types (ENUMs parsed as STRUCT).

        NOTE: Does NOT resolve type aliases because `type X = Y` creates a distinct type
        in Saw, not a transparent alias. Use _resolve_type_alias() when you need to
        check the underlying type structure (e.g., to check if something is Optional).

        THE PRELUDE GATE'S ONE ENTRY POINT (design 194 unit 4, DF-188k/DF-193d).
        Every written annotation reaches resolution, so gating here covers every
        position a user can write a type in — and the gate judges
        `SawType.written_name`, the parser's record of the author's own
        spelling, so a compiler-built type is never judged and a qualified
        `data.Data` is never mistaken for a bare `Data`. See
        `TypeChecker._gate_resolved_type`.
        """
        self._gate_written_type(saw_type)
        if saw_type.kind == TypeKind.STRUCT and saw_type.struct_name:
            struct_name = self._canonical_type_name(saw_type.struct_name)

            # `Optional<T>` IS `T?` (DF-174d). `Result` was wired up as a name
            # from the start and `Optional` never was, so `let a: Optional<Int>`
            # resolved to an opaque nominal struct nothing could satisfy and the
            # mismatch named a type with no members. The asymmetry was
            # historical: the prelude lists `Optional` as a core name and the
            # spec documents `Optional.take`, so users write it. It is a
            # SPELLING, resolved here rather than registered as a nominal type —
            # `Optional<Int>` and `Int?` are one type, and this is also how a
            # nested optional gets a written form (`Optional<Int?>`).
            if (struct_name == "Optional"
                    and self.get_struct_info(struct_name, from_type=saw_type) is None
                    and self.get_enum_info(struct_name, from_type=saw_type) is None):
                args = saw_type.type_args or []
                if len(args) != 1:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`Optional` takes exactly one type argument, but "
                        f"{len(args)} were given",
                        getattr(saw_type, 'line', 0) or 0,
                        getattr(saw_type, 'column', 0) or 1,
                        hint="write `Optional<T>`, or the postfix `T?`")
                    return SawType(TypeKind.OPTIONAL, inner_type=None)
                return SawType(TypeKind.OPTIONAL,
                               inner_type=self._resolve_type(args[0]))

            # Handle module-qualified types (e.g., lib.Point, mod.lib.Color)
            if '.' in struct_name:
                found = self._resolve_qualified_symbol(struct_name)
                if found is not None:
                    symbol, identity = found
                    resolved_args = [self._resolve_type(t) for t in saw_type.type_args] if saw_type.type_args else None
                    if symbol.kind == SymbolKind.STRUCT:
                        if resolved_args:
                            resolved_args = self._append_default_type_args(identity, resolved_args)
                        return SawType(TypeKind.STRUCT, struct_name=identity, type_args=resolved_args, symbol=symbol)
                    elif symbol.kind == SymbolKind.ENUM:
                        if resolved_args:
                            resolved_args = self._append_default_type_args(identity, resolved_args, is_enum=True)
                        return SawType(TypeKind.ENUM, enum_name=identity, type_args=resolved_args, symbol=symbol)

            # Check if this is actually an enum (NOT a type alias - those stay as STRUCT)
            # Use get_enum_info which searches imported modules
            enum_symbol = self.get_enum_info(struct_name, from_type=saw_type)
            if enum_symbol:
                resolved_args = [self._resolve_type(t) for t in saw_type.type_args] if saw_type.type_args else None
                if resolved_args:
                    resolved_args = self._append_default_type_args(struct_name, resolved_args, is_enum=True)
                return SawType(TypeKind.ENUM, enum_name=struct_name, type_args=resolved_args, symbol=enum_symbol)
            # Recursively resolve type args
            if saw_type.type_args:
                resolved_args = [self._resolve_type(t) for t in saw_type.type_args]
                # Design 37: fill omitted trailing type args from their defaults
                # (`Vector<Int>` -> `Vector<Int, Global>`) so the canonical
                # identity is fixed at resolution time.
                resolved_args = self._append_default_type_args(struct_name, resolved_args)
                return SawType(TypeKind.STRUCT, struct_name=struct_name, type_args=resolved_args)
            # Design 144: a bare named type still has to come out of resolution
            # carrying its identity. This arm used to hand `saw_type` straight
            # back, which is exactly the case (a non-generic struct reference)
            # the DF-142a repro is made of.
            if struct_name != saw_type.struct_name:
                import dataclasses
                return dataclasses.replace(saw_type, struct_name=struct_name)
        elif saw_type.kind == TypeKind.REFERENCE and saw_type.inner_type:
            # DF-140c: resolve the REFERENT. Every other composite here recursed
            # into its parts and a reference did not, so `&qual.Section` kept the
            # module-qualified spelling as an unresolved nominal name while the
            # by-value `qual.Section` resolved fine. The parameter type then
            # matched nothing: the method lookup failed (reported as `undefined
            # variable raw` at the `guard let` BINDING, three errors downstream of
            # the real one), and a call site was told `&qual.Section` and
            # `&Section` were different types.
            resolved_inner = self._resolve_type(saw_type.inner_type)
            return SawType(TypeKind.REFERENCE, inner_type=resolved_inner,
                           reference_mutable=saw_type.reference_mutable)
        elif (saw_type.kind == TypeKind.EXISTENTIAL
              and saw_type.existential_trait
              and '.' in saw_type.existential_trait):
            # DF-150a: `&any qual.Named`. The same gap DF-140c closed for
            # references, one composite over: every downstream consumer — method
            # dispatch on the erased value, the conformance check at an erasure
            # site, vtable selection — compares trait names, and none of them
            # knows how to strip a module qualifier. Resolve it to the trait's
            # own identity HERE, so a qualified spelling and a bare one are the
            # same type from this point on. Design 150 makes this reachable:
            # under a whole-module import the qualifier is the ONLY way to name
            # an imported trait.
            module_part, _, simple = saw_type.existential_trait.rpartition('.')
            trait = self.get_trait_info(
                simple, qualified_path=saw_type.existential_trait)
            if trait is not None:
                import dataclasses
                identity = getattr(trait, 'type_identity', "") or simple
                return dataclasses.replace(saw_type, existential_trait=identity)
        elif saw_type.kind == TypeKind.OPTIONAL and saw_type.inner_type:
            # Recursively resolve optional inner types
            resolved_inner = self._resolve_type(saw_type.inner_type)
            return SawType(TypeKind.OPTIONAL, inner_type=resolved_inner)
        elif saw_type.kind == TypeKind.TUPLE and saw_type.element_types:
            # Recursively resolve tuple element types
            resolved_elements = [self._resolve_type(t) for t in saw_type.element_types]
            return SawType(TypeKind.TUPLE, element_types=resolved_elements,
                           tuple_field_names=saw_type.tuple_field_names)
        elif saw_type.kind == TypeKind.ARRAY and saw_type.array_element_type:
            # design 148: the element resolves like any type, and a length
            # written as an expression is folded here — `[Int8; 2 * 128]`
            # becomes `[Int8; 256]`. A length that mentions a const generic
            # parameter cannot be folded in the abstract half of a generic body
            # and keeps its expression until substitution supplies the value.
            resolved_elem = self._resolve_type(saw_type.array_element_type)
            size = saw_type.array_size
            if size is None and saw_type.array_size_expr is not None:
                size = self._try_const_value(saw_type.array_size_expr)
            return SawType(TypeKind.ARRAY, array_element_type=resolved_elem,
                           array_size=size,
                           array_size_expr=saw_type.array_size_expr)
        elif saw_type.kind == TypeKind.CONST_VALUE:
            # A const generic ARGUMENT written as an expression (`FixedBuf<N * 2>`).
            if saw_type.const_value is None and saw_type.array_size_expr is not None:
                value = self._try_const_value(saw_type.array_size_expr)
                if value is not None:
                    import dataclasses
                    return dataclasses.replace(saw_type, const_value=value)
            return saw_type
        elif saw_type.kind == TypeKind.ENUM and saw_type.enum_name:
            enum_name = self._canonical_type_name(saw_type.enum_name)
            if saw_type.type_args:
                # Recursively resolve enum type args
                resolved_args = [self._resolve_type(t) for t in saw_type.type_args]
                resolved_args = self._append_default_type_args(enum_name, resolved_args, is_enum=True)
                return SawType(TypeKind.ENUM, enum_name=enum_name, type_args=resolved_args, symbol=saw_type.symbol)
            if enum_name != saw_type.enum_name:
                import dataclasses
                return dataclasses.replace(saw_type, enum_name=enum_name)
        elif saw_type.kind == TypeKind.FUNCTION:
            # Recursively resolve function param and return types
            resolved_params = [self._resolve_type(t) for t in (saw_type.param_types or [])]
            resolved_return = self._resolve_type(saw_type.func_return_type) if saw_type.func_return_type else None
            # `func_escaping_stamped` rides along: resolution rebuilds the node,
            # and losing the bit would make the next `_stamp_escaping_roles`
            # read our own stamp as an author-written `escaping`.
            return SawType(TypeKind.FUNCTION, param_types=resolved_params, func_return_type=resolved_return, func_is_sync=saw_type.func_is_sync, func_is_escaping=saw_type.func_is_escaping, func_escaping_stamped=saw_type.func_escaping_stamped, func_is_unsafe=saw_type.func_is_unsafe)
        return saw_type

    # ---------------------------------------------------------------- DF-172j
    # A module `static` in a const-required position.
    #
    # Design 148 fixed the constants an array length, a repeat count and a const
    # generic argument accept: literals, const generic parameters, arithmetic
    # over them. That left a kernel with no way to have ONE checked source for a
    # region size — `static REGION_SIZE: Int = 65536` beside `[UInt8;
    # REGION_SIZE]` was a clean error (DF-172f) and the workaround was a named
    # array type plus `sizeof`. The subset that folds is the subset that is
    # already a literal by the time anything asks: an `Int`/`UInt` static whose
    # initializer IS a plain integer literal. Everything else about a static —
    # `unsafe static var`, a String, a struct literal — keeps DF-172f's error,
    # now saying WHICH of the two things went wrong.
    #
    # Three moving parts, and the ordering is why they are three:
    #   * `_collect_const_statics` indexes the declarations BEFORE anything is
    #     registered, because a struct field's `[UInt8; REGION_SIZE]` is resolved
    #     in the struct pass and statics are registered four passes later.
    #   * `_register_static` copies the answer onto the SYMBOL, which is what
    #     travels to an importing module (under a rename, even).
    #   * `_stamp_const_names` writes the value onto the identifier NODE, so
    #     the evaluator — and codegen, which re-evaluates the same nodes with no
    #     namespace in hand — reads a number instead of a name.
    #
    # design 185 unit 3 widened the third part from identifiers to the MEMBER
    # ACCESSES a constant can name, on the same terms and for the same reason: a
    # length in TYPE position is never type-checked, so nothing else was going to
    # stamp `Perm.Read`, `Int.max` or `dep.REGION_SIZE` there. That is DF-172l's
    # remaining half — the bare and qualified spellings of one static now fold to
    # one number — and it is what makes a raw-backed enum's case usable as the
    # constant it already is.
    # ------------------------------------------------------------------------

    def _collect_const_statics(self, program) -> None:
        """Index this AST's `static`s by (defining module, name) -> binding.

        Runs before registration, so the answer is computed from the type AS
        WRITTEN — which is also the only moment it can be, since registration
        overwrites `static.type` with the resolved one.

        IN DECLARATION ORDER (design 186 unit 7). Design 172j read a literal off
        each initializer independently; the const-foldable tier means an
        initializer may NAME an earlier static (`static MASK: Int = PAGE - 1`),
        so each one is evaluated against the table built so far and its answer
        goes in before the next is read. Forward and self references therefore
        fold to nothing and say so — that IS the cycle rule, and it falls out of
        the order rather than needing a graph.
        """
        table = getattr(self, '_const_static_decls', None)
        if table is None:
            table = {}
            self._const_static_decls = table
        # DF-232c: fold any case value written as a const EXPRESSION into the
        # plain int every later consumer reads. FIRST, because the very next
        # line reads those ints.
        self._fold_enum_raw_values(program)
        # A raw-backed enum's case values, read off the AST: registration has
        # not run, so `Perm.Read` has no symbol to resolve against yet, and a
        # flag-enum static (`static RW: UInt8 = Perm.Read | Perm.Write`) needs
        # the numbers HERE. Declaration order does not apply between enums and
        # statics: an enum's cases are pinned by its own declaration.
        raws = self._ast_enum_raw_values(program)
        for static in getattr(program, 'statics', []) or []:
            module = self._vis_module_for_source(
                getattr(static, 'source_file', None))
            key = (module, static.name)
            # A duplicate is an error at registration; the FIRST declaration is
            # the one that survives it, so it is the one indexed here.
            if key in table:
                continue
            table[key] = self._static_const_binding(static, module, raws)

    def _fold_enum_raw_values(self, program) -> None:
        """Fold every raw-backed enum case value written as a const EXPRESSION
        into the plain int the rest of the compiler reads (DF-232c).

        A flags enum wants to say WHICH BIT it means — `case ThreadCreate =
        1 << 8`, not `= 256` — and design 185 already folds `<<` in const
        positions. What it did not cover was a case value's OWN initializer,
        which the grammar admitted as a bare integer literal and nothing else.

        WHY HERE, and not later: `raw_value` is read by twelve consumers across
        four phases, and the earliest is `_ast_enum_raw_values` — called by
        `_collect_const_statics` BEFORE registration, so a flag-enum static
        (`static RW: UInt8 = Perm.Read | Perm.Write`) can see the numbers.
        Folding at this seam means every one of those consumers still reads a
        plain int and none of them changed.

        WHAT FOLDS: literals (hex and binary included), and arithmetic, bitwise
        and shift operators over them, at platform width — `const_eval`'s
        ordinary tier. NOT a `static` or another enum's case: those are
        resolved by stamping leaves against a table built in DECLARATION order,
        and an enum's cases are pinned by its own declaration, which is why
        `_collect_const_statics` reads all enums BEFORE any static. Naming one
        here would be a forward reference to a table that does not exist yet,
        so it is refused by name rather than half-supported.

        Design 145's no-auto-increment rule is untouched: a folded `1 << 8`
        states its value as exactly as `256` does, and says which bit while
        doing it. The range check against the declared backing is unchanged and
        still runs at registration, on the folded int.
        """
        from const_eval import const_eval, ConstEvalError
        for enum in getattr(program, 'enums', []) or []:
            for variant in getattr(enum, 'variants', []) or []:
                expr = getattr(variant, 'raw_value_expr', None)
                if expr is None or variant.raw_value is not None:
                    continue
                try:
                    value = const_eval(expr, width=self.platform_int_width)
                except ConstEvalError:
                    value = None
                if isinstance(value, bool) or not isinstance(value, int):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"raw value for case `{variant.name}` of enum "
                        f"`{enum.name}` is not a compile-time constant",
                        variant.raw_line, variant.raw_column,
                        source_file=getattr(enum, 'source_file', None),
                        hint="a case's raw value is an integer CONSTANT "
                             "EXPRESSION: literals (`0x100`, `0b1010`) and "
                             "arithmetic, bitwise and shift operators over "
                             "them, so a flag is spelled `1 << 8`. It may not "
                             "name a `static` or another enum's case — an "
                             "enum's cases are fixed by its own declaration, "
                             "before any of those are known")
                    continue
                variant.raw_value = value

    def _ast_enum_raw_values(self, program):
        """`{(enum name, case name): value}` for every raw-BACKED enum in this
        AST, read straight off the declarations."""
        out = {}
        for enum in getattr(program, 'enums', []) or []:
            if getattr(enum, 'raw_type', None) is None:
                continue
            for variant in getattr(enum, 'variants', []) or []:
                value = getattr(variant, 'raw_value', None)
                if value is not None:
                    out[(enum.name, variant.name)] = int(value)
        return out

    def _static_const_binding(self, static, module=(), raws=None):
        """`(value, reason)` — the integer this `static` denotes in a constant
        position, or the reason it denotes none.

        The reason is phrased to complete "<reason> is not allowed here", and
        NAMES the static: the whole point of the rule is that a static may be
        written here now, so a refusal has to say which static and why rather
        than reading as "no static may".
        """
        name = static.name
        if getattr(static, 'is_var', False):
            # An `unsafe static var` is mutable, so its value is a fact about
            # the running program, not about the source.
            return None, f"the mutable static `{name}`"
        declared = getattr(static, 'type', None)
        kind = getattr(declared, 'kind', None)
        if kind not in (TypeKind.INT, TypeKind.UINT):
            spelled = f"`{declared}` " if declared is not None else ""
            return None, f"the {spelled}static `{name}`"
        init = getattr(static, 'initializer', None)
        if init is None:
            return None, f"the uninitialized static `{name}`"
        value = self._fold_static_decl(init, module, raws or {})
        if value is None:
            return None, f"the computed static `{name}`"
        return value, None

    def _fold_static_decl(self, expr, module, raws):
        """Fold a static's initializer against the declarations seen SO FAR.

        A pre-registration evaluation, so it resolves its own two kinds of name
        off the AST rather than off the symbol table: an earlier static of this
        module (the declaration-order rule) and a raw-backed enum case. A name
        it cannot resolve — a forward reference, a self reference, anything
        else — simply fails to fold, and the caller reports the static as
        computed.
        """
        from const_eval import const_eval, ConstEvalError
        from ast_nodes import Identifier, UnaryOp, BinaryOp, CastExpr, MemberAccess
        table = getattr(self, '_const_static_decls', None) or {}

        def stamp(node):
            if isinstance(node, UnaryOp):
                stamp(node.operand)
            elif isinstance(node, BinaryOp):
                stamp(node.left)
                stamp(node.right)
            elif isinstance(node, CastExpr):
                stamp(node.expr)
            elif isinstance(node, Identifier):
                earlier = table.get((module, node.name))
                if earlier is not None and earlier[0] is not None:
                    node.const_static_value = earlier[0]
            elif isinstance(node, MemberAccess):
                owner = getattr(node.object, 'name', None)
                raw = raws.get((owner, node.member))
                if raw is not None:
                    node.enum_raw_value = raw

        stamp(expr)
        try:
            value = const_eval(expr, width=self.platform_int_width)
        except ConstEvalError:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value

    def _const_static_lookup(self, name: str):
        """`(value, reason)` for `name` read as a module static from here, or
        `(None, None)` when it is not one.

        Visibility is the namespace's answer, asked exactly as an ordinary read
        of the name would ask it — so a module-private static of another module
        is invisible here, and a `public` one reached through an import is not.
        The declaration table is the fallback for the case the symbol table
        cannot cover: a static of THIS module that has not been registered yet.
        """
        sym = self.namespace.get_static(name, self._accessor_vis_module())
        if sym is not None and self.namespace.is_accessible(name):
            return getattr(sym, 'const_value', None), \
                getattr(sym, 'const_reject', None)
        table = getattr(self, '_const_static_decls', None) or {}
        return table.get((self._accessor_vis_module(), name), (None, None))

    def _stamp_const_names(self, expr) -> None:
        """Resolve the names a constant expression reads, onto its own nodes.

        Name resolution order mirrors an ordinary read (`_check_identifier`):
        a local binding wins, then a const generic parameter, then a static. The
        local check is what keeps the derived shadow legal — `let REGION_SIZE =
        REGION_SIZE + 1` is a binding design 100 allows, and folding the static
        into `[0; REGION_SIZE]` under it would silently compile the wrong
        length.
        """
        from ast_nodes import Identifier, UnaryOp, BinaryOp, CastExpr, MemberAccess
        if isinstance(expr, UnaryOp):
            self._stamp_const_names(expr.operand)
            return
        if isinstance(expr, BinaryOp):
            self._stamp_const_names(expr.left)
            self._stamp_const_names(expr.right)
            return
        if isinstance(expr, CastExpr):
            self._stamp_const_names(expr.expr)
            return
        if isinstance(expr, MemberAccess):
            self._stamp_const_member(expr)
            return
        if not isinstance(expr, Identifier):
            return
        if expr.const_static_value is not None or \
                expr.const_static_reject is not None:
            return
        scope = getattr(self, 'current_scope', None)
        if scope is not None and scope.lookup(expr.name):
            return
        if expr.name in self._const_param_types() or \
                expr.name in self._const_param_env():
            return
        value, reason = self._const_static_lookup(expr.name)
        if value is not None:
            expr.const_static_value = value
        elif reason is not None:
            expr.const_static_reject = reason

    @contextmanager
    def _const_position(self):
        """Check the enclosed expression as a CONSTANT (design 185 unit 3).

        A repeat count and a `static_assert` condition are type-checked before
        they are folded, which is what lets an ordinary type error in one be
        reported as itself. The one rule that needs to know it is standing in a
        constant is the flag-enum reading: `Perm.Read | Perm.Write` is a bit set
        over compile-time-known tags HERE, and stays a refusal in running code,
        where the operands would be enum-typed VALUES (design 185 unit 4).
        """
        depth = getattr(self, '_const_position_depth', 0)
        self._const_position_depth = depth + 1
        try:
            yield
        finally:
            self._const_position_depth = depth

    def _in_const_position(self) -> bool:
        """Whether the expression being checked is required to be constant."""
        return getattr(self, '_const_position_depth', 0) > 0

    def _stamp_const_member(self, expr) -> None:
        """The MEMBER ACCESSES a constant may name (design 185 unit 3).

        Three shapes, and they are the three the evaluator already understands
        in an expression — `Int.max`, a raw-BACKED enum's case, and a module
        `static`, the last two in both the bare and the qualified spelling. In
        an EXPRESSION the ordinary member-access check stamps all of them; a
        declared array length is the position that is never checked as an
        expression at all, so without this it could name none of them.

        Resolution is asked exactly as an ordinary read asks it, which is what
        `_module_qualifier` and `get_enum_info` are: a local named `Perm` or
        `dep` wins, a private static of another module is invisible, and a
        member this file may not see stamps nothing and falls through to the
        evaluator's "this member access is not allowed here".
        """
        from ast_nodes import Identifier, MemberAccess
        if expr.int_limit is not None or expr.enum_raw_value is not None or \
                expr.const_static_value is not None or \
                expr.const_static_reject is not None:
            return
        obj = expr.object
        if isinstance(obj, Identifier):
            scope = getattr(self, 'current_scope', None)
            if scope is not None and scope.lookup(obj.name):
                return
            limit_kind = self._INT_LIMIT_TYPE_KINDS.get(obj.name)
            if limit_kind is not None and expr.member in ("max", "min"):
                expr.int_limit = (obj.name, expr.member)
                return
            enum_info = self.get_enum_info(obj.name)
            if enum_info is not None:
                self._stamp_enum_raw_value(expr, enum_info)
                return
            self._stamp_qualified_const(expr, obj.name, expr.member)
            return
        # `dep.Perm.Read`: the qualifier resolves the ENUM, this hop the case.
        if isinstance(obj, MemberAccess) and isinstance(obj.object, Identifier):
            enum_info = self._qualified_enum_info(obj.object.name, obj.member)
            if enum_info is not None:
                self._stamp_enum_raw_value(expr, enum_info)

    def _qualified_module_symbol(self, qualifier: str, name: str):
        """`qualifier.name` resolved through an import, or None (design 150)."""
        module_sym = self._module_qualifier(qualifier)
        if module_sym is None or not module_sym.namespace:
            return None
        return module_sym.namespace.resolve(
            name, check_visibility=True,
            accessor_module=self._accessor_vis_module(),  # DF-232j
            through_import=True)

    def _qualified_enum_info(self, qualifier: str, name: str):
        """The enum `qualifier.name` names, or None."""
        from namespace import SymbolKind
        symbol = self._qualified_module_symbol(qualifier, name)
        if symbol is None or symbol.kind != SymbolKind.ENUM:
            return None
        identity = getattr(symbol, 'type_identity', "") or name
        return self.get_enum_info(identity)

    def _stamp_qualified_const(self, expr, qualifier: str, name: str) -> None:
        """`dep.REGION_SIZE` in a constant — DF-172l's remaining half.

        The bare spelling folds through the SYMBOL (`_const_static_lookup`), and
        so does this one: the qualifier only changes how the symbol is found, not
        what it means, so a renamed import and a `{...}` selection agree with the
        module's own reading of its static.
        """
        from namespace import SymbolKind
        symbol = self._qualified_module_symbol(qualifier, name)
        if symbol is None:
            return
        if symbol.kind == SymbolKind.ENUM:
            identity = getattr(symbol, 'type_identity', "") or name
            enum_info = self.get_enum_info(identity)
            if enum_info is not None:
                # `dep.Perm` as a whole is a TYPE, not a value; only the case
                # hop below it is constant. Nothing to stamp here.
                return
        if symbol.kind != SymbolKind.STATIC:
            return
        value = getattr(symbol, 'const_value', None)
        reason = getattr(symbol, 'const_reject', None)
        if value is not None:
            expr.const_static_value = value
        elif reason is not None:
            expr.const_static_reject = reason

    def _walk_declared_types(self, program, visit) -> None:
        """Call `visit(t)` on every type WRITTEN in this AST, sub-types included.

        The declared positions are what a `static` in a constant has to reach. A
        local's annotation is resolved when the statement checker gets to it, but
        a struct FIELD's type is stored exactly as written and is never resolved
        before codegen reads it — so a `[UInt8; REGION_SIZE]` field would arrive
        there with no length at all while the `var` spelling of the same type
        worked.

        Reflective over sub-types rather than a hand-listed set of fields: a
        length or a const argument can sit anywhere a type can
        (`Vector<[UInt8; SIZE]>`, a parameter of a function type, an optional
        payload), and a list that missed one would fail silently, in codegen, on
        the one spelling nobody wrote a test for.
        """
        import dataclasses
        seen = set()

        def walk(t):
            if not isinstance(t, SawType) or id(t) in seen:
                return
            seen.add(id(t))
            visit(t)
            for f in dataclasses.fields(t):
                v = getattr(t, f.name, None)
                if isinstance(v, SawType):
                    walk(v)
                elif isinstance(v, (list, tuple)):
                    for item in v:
                        if isinstance(item, SawType):
                            walk(item)

        def walk_signature(fn):
            for p in getattr(fn, 'parameters', []) or []:
                walk(getattr(p, 'type', None))
            walk(getattr(fn, 'return_type', None))

        for struct in getattr(program, 'structs', []) or []:
            for f in getattr(struct, 'fields', []) or []:
                walk(getattr(f, 'type', None))
        for enum in getattr(program, 'enums', []) or []:
            for variant in getattr(enum, 'variants', []) or []:
                for payload in (variant.associated_types or []):
                    walk(payload[1] if isinstance(payload, tuple) else payload)
        for fn in getattr(program, 'functions', []) or []:
            walk_signature(fn)
        for ext in getattr(program, 'extensions', []) or []:
            for method in getattr(ext, 'methods', []) or []:
                walk_signature(method)
        for trait in getattr(program, 'traits', []) or []:
            for tm in getattr(trait, 'methods', []) or []:
                walk_signature(tm)
        for block in getattr(program, 'extern_blocks', []) or []:
            for fn in getattr(block, 'functions', []) or []:
                walk_signature(fn)
        for static in getattr(program, 'statics', []) or []:
            walk(getattr(static, 'type', None))
        for td in getattr(program, 'type_definitions', []) or []:
            walk(getattr(td, 'defined_type', None))

    def _fold_const_lengths_in_program(self, program) -> None:
        """Fold every DECLARED array length in this AST, in place.

        Runs BEFORE registration, since registration copies field types into the
        struct symbol. Only lengths that fold TO something are touched: a
        `[T; N]` on a const generic parameter has no value in the abstract body
        and keeps its expression, exactly as design 148 wrote it.
        """
        def fold(t):
            if t.kind == TypeKind.ARRAY and t.array_size is None and \
                    t.array_size_expr is not None:
                value = self._try_const_value(t.array_size_expr)
                if value is not None and not self._reject_negative_length(
                        value, t.array_size_expr):
                    t.array_size = value
        self._walk_declared_types(program, fold)

    def _fold_const_type_args_in_program(self, program) -> None:
        """Fold a bare-NAME const generic ARGUMENT that is a `static` (DF-172j).

        The twin of the length pass, one phase later: this one needs the
        REFERENCED type's parameter list to know that `FixedBuf<CAP>`'s argument
        lands on a const parameter rather than a type one, so it cannot run
        until structs and enums are registered. It mutates in place, which
        reaches the already-registered struct symbol too — the symbol holds the
        same field-type objects the AST does.
        """
        def fold(t):
            if t.kind == TypeKind.STRUCT and t.struct_name and t.type_args:
                info = self.get_struct_info(t.struct_name)
            elif t.kind == TypeKind.ENUM and t.enum_name and t.type_args:
                info = self.get_enum_info(t.enum_name)
            else:
                return
            params = getattr(info, 'type_params', None) if info else None
            if params:
                t.type_args = self._const_static_args(t.type_args, params)
        self._walk_declared_types(program, fold)

    def _reject_negative_length(self, value: int, expr, line: int = 0,
                                column: int = 0) -> bool:
        """Report a NEGATIVE array length, returning whether it did (DF-172k).

        `[UInt8; 2 - 3]` folded to -1 and reached llvmlite as `[-1 x i8]`, which
        came back as "internal compiler error: LLVM IR parsing error". The
        repeat-count spelling of the same rule has said "repeat count is
        negative" since design 148; the type position had not, and DF-172j gives
        the fold one more way to arrive here, since a static may be negative.
        """
        if value >= 0:
            return False
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"array length is negative (`{value}`)",
            getattr(expr, 'line', 0) or line,
            getattr(expr, 'column', 0) or column,
            hint="an array length counts elements, so it starts at 0")
        return True

    def _check_declared_array_lengths(self, t, what: str, line: int,
                                      column: int, seen=None) -> None:
        """Report a DECLARED array length that folded to nothing (DF-172k).

        Every other position a `[T; N]` is written reaches codegen, which owns
        the requirement (design 148) — but a BINDING's annotation does not: when
        the initializer supplies its own type the annotation is only compared
        against it, and a length of `None` compares equal to anything. So
        `var buf: [UInt8; NOPE] = [0; 4]` compiled clean, with the annotation
        silently ignored, and under DF-172j it would read as the compiler
        ACCEPTING a static it actually just dropped. Asked here, where the
        annotation is resolved.

        A length that mentions a const generic parameter is constant with no
        value in the abstract body and is left alone, exactly as everywhere else.
        """
        import dataclasses
        from const_eval import const_eval, ConstEvalError, CONST_LENGTH_HINT
        if not isinstance(t, SawType):
            return
        seen = set() if seen is None else seen
        if id(t) in seen:
            return
        seen.add(id(t))
        expr = t.array_size_expr
        if t.kind == TypeKind.ARRAY and isinstance(t.array_size, int) and \
                t.array_size < 0:
            if self._reject_negative_length(t.array_size, expr, line, column):
                # Do not carry a length nothing can build any further: leaving
                # it unfolded is what keeps the report to ONE error instead of
                # a cascade of mismatches against `[UInt8; -1]`.
                t.array_size = None
        if t.kind == TypeKind.ARRAY and t.array_size is None and \
                expr is not None and not self._mentions_const_param(expr):
            self._stamp_const_names(expr)
            try:
                const_eval(expr, env=self._const_param_env(),
                           width=self.platform_int_width)
            except ConstEvalError as e:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"array length is not a compile-time constant: {e.what} "
                    f"is not allowed here",
                    e.line or line, e.column or column, hint=CONST_LENGTH_HINT)
        for f in dataclasses.fields(t):
            v = getattr(t, f.name, None)
            if isinstance(v, SawType):
                self._check_declared_array_lengths(v, what, line, column, seen)
            elif isinstance(v, (list, tuple)):
                for item in v:
                    if isinstance(item, SawType):
                        self._check_declared_array_lengths(
                            item, what, line, column, seen)

    def _try_const_value(self, expr):
        """Fold a constant expression, or return None if it cannot be folded yet.

        Silent by design (design 148): the same length expression is resolved
        many times over a compile, and in the abstract half of a generic body it
        legitimately has no value. The position that OWNS the requirement — a
        repeat count, a declared array length reaching codegen — reports it.
        """
        from const_eval import const_eval, ConstEvalError
        self._stamp_const_names(expr)
        try:
            value = const_eval(expr, env=self._const_param_env(),
                               width=self.platform_int_width)
        except ConstEvalError:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value

    def _prepare_ok_payload(self, value_expr, value_type, ok_type):
        """Make `value_expr` a well-formed Ok PAYLOAD for `ok_type` (DF-140d).

        `Result<T?, E>` needs a DOUBLE wrap — into the Optional, then into the
        Result — and neither direction was performed, so both spellings were
        internal compiler errors rather than working code or a clean message:

            return None        -> "None literal has no type information"
            return Cfg(v: 1)   -> "Can only insert {i1, %Cfg} at [0] in
                                   {{i1, %Cfg}}: got %Cfg"

        Two shapes to repair, both only when the Ok type is an Optional:

        * a bare `None` carries no payload type of its own, so it is stamped with
          the Ok type before it is wrapped (codegen reads that stamp to size the
          `{i1, T}` it builds);
        * a bare payload value is wrapped in `OptionalWrap` first, so the
          ResultOkWrap around it receives the `T?` it is declared to hold.

        Returns the expression to put inside the `ResultOkWrap`. Anything already
        optional (an `Optional<T>`-typed expression) is handed back untouched —
        matching a `Result<T?, E>` and binding through `if let` always worked, so
        the shape was only ever broken at the auto-wrap boundary.
        """
        if value_expr is None or ok_type is None or not ok_type.is_optional():
            return value_expr
        if value_type is not None and value_type.is_none_literal():
            self._annotate_none_in_expr(value_expr, ok_type)
            return value_expr
        if value_type is not None and not value_type.is_optional():
            from ast_nodes import OptionalWrap as _OW
            return _OW(value=value_expr, target_type=ok_type,
                       line=getattr(value_expr, 'line', 0),
                       column=getattr(value_expr, 'column', 0))
        return value_expr

    def _optional_depth(self, t: Optional[SawType]) -> int:
        """How many optional layers `t` names, resolving aliases as it peels.

        `Int??` is 2, `Optional<Int?>` is the same 2 under the other spelling,
        and anything else is 0. Used where the WRAP rule must not be allowed to
        paper over a depth difference (DF-174h) — `_types_compatible` admits
        `T` into `T?` by design, which is right at a slot and wrong at a `??`
        default, where the peel has already been counted."""
        depth = 0
        while t is not None and depth < 64:
            t = self._resolve_type_alias(t)
            if t is None or not t.is_optional():
                break
            depth += 1
            t = t.inner_type
        return depth

    def _unresolved_qualified_name(self, t: Optional[SawType]):
        """The module-qualified type name in `t` that did not resolve, or None.

        DF-140c: a dotted spelling is unambiguous — the author wrote `mod.Type`,
        so `mod` has to be a module and `Type` has to exist in it. There is no
        generic parameter, `Self`, or forward reference that could legitimately
        survive resolution still carrying a dot. So a STRUCT type whose name
        still has one after `_resolve_type` ran is a genuine failure worth its own
        diagnostic, rather than the three downstream errors it used to produce (a
        `guard let` over an unresolvable method reported the BINDING as undefined,
        which is the silent part and the worst of it).

        Looks through the wrappers a signature puts around a nominal type.
        """
        if t is None:
            return None
        if t.kind in (TypeKind.REFERENCE, TypeKind.OPTIONAL) and t.inner_type:
            return self._unresolved_qualified_name(t.inner_type)
        if t.kind == TypeKind.STRUCT and t.struct_name and '.' in t.struct_name:
            return t.struct_name
        return None

    def _unknown_generic_type_name(self, t):
        """A written type name with ARGUMENTS that resolves to nothing, or None.

        DF-174d's second half: a bare unknown name is genuinely indistinguishable
        from a type parameter or an associated type at resolution time, so
        `let a: Frobnicate<Int> = 5` reported a mismatch against an opaque
        nominal type rather than saying the name means nothing. Type ARGUMENTS
        settle it — a type parameter takes none, and neither does an associated
        type — so a name carrying them and resolving to no struct, enum or alias
        is a name the program does not define.

        Looks through the wrappers an annotation puts around a nominal type.
        """
        if t is None:
            return None
        if t.kind in (TypeKind.REFERENCE, TypeKind.OPTIONAL) and t.inner_type:
            return self._unknown_generic_type_name(t.inner_type)
        if t.kind != TypeKind.STRUCT or not t.struct_name or not t.type_args:
            return None
        name = t.struct_name
        if '.' in name:
            return None          # `_check_qualified_type_resolves` owns this one
        if (self.get_struct_info(name, from_type=t) is not None
                or self.get_enum_info(name, from_type=t) is not None
                or self.get_type_alias_info(name) is not None):
            return None
        if name in (getattr(self, 'current_type_params', None) or {}):
            return None
        return name

    def _check_type_name_resolves(self, t, context: str, line: int, column: int,
                                  source_file=None):
        """Report a written type name that resolves to nothing (DF-174d)."""
        name = self._unknown_generic_type_name(t)
        if name is None:
            return
        self._error(
            ErrorKind.UNKNOWN_TYPE,
            f"unknown type `{name}` in {context}",
            line, column, source_file=source_file,
            hint="check the spelling, and that the module defining it is "
                 "imported")

    def _check_qualified_type_resolves(self, t, context: str, line: int, column: int,
                                       source_file=None):
        """Report a module-qualified type that did not resolve (DF-140c)."""
        name = self._unresolved_qualified_name(t)
        if name is None:
            return
        module, _, simple = name.rpartition('.')
        self._error(
            ErrorKind.UNKNOWN_TYPE,
            f"type `{name}` in {context} does not resolve",
            line, column, source_file=source_file,
            hint=f"`{module}` must be an imported module exporting a public "
                 f"`{simple}` — check the import and that `{simple}` is `public`"
        )

    def _stamp_escaping_roles(self, t: Optional[SawType], is_param: bool = False,
                              report_at=None):
        """Stamp function types with their escaping bit by syntactic role (design
        16/29).

        A function type in PARAMETER position is non-escaping by default (the
        `escaping` marker in its post-parameter slot opts in — the parser already
        set the bit). A function type in ANY OTHER role — struct field, enum
        payload, function return, let/var binding annotation, or nested inside a
        container in those roles — is IMPLICITLY escaping: the value it names
        outlives the current call, so it must be safe to store. Writing the
        marker in a non-parameter role is redundant and reported once via
        `report_at=(line, column)`.

        Only the TOP LEVEL of a parameter type is a parameter role; everything
        nested inside one names storage the caller already owns. That is why a
        REFERENCE recurses with `is_param=False` (DF-216e): `out: &var
        Vector<() sync -> Int>` is a parameter, but the element it lends is a
        container slot that outlives the call, and leaving it unstamped told
        `_check_closure` that `out.push({ n * 2 })` was a non-escaping
        argument — so a closure borrowing the caller's frame was stored in a
        Vector that outlived it.

        Called on declared types at registration/binding time so that every
        VALUE carries the correct bit and the variance check in
        `_check_value_transfer` reads it directly.
        """
        if t is None:
            return t
        if t.kind == TypeKind.FUNCTION:
            if not is_param:
                # Only an AUTHOR-written marker is redundant. This runs over one
                # declared type more than once (the coroutine transform re-enters
                # the front half), so a bit this pass set on a previous visit is
                # the compiler's own stamp, not a second `escaping` in the
                # source — see `SawType.func_escaping_stamped`.
                if (t.func_is_escaping and not t.func_escaping_stamped
                        and report_at is not None):
                    line, col = report_at
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        "redundant `escaping` — closure types outside parameter "
                        "position are always escaping",
                        line, col
                    )
                t.func_is_escaping = True
                t.func_escaping_stamped = True
            for p in (t.param_types or []):
                self._stamp_escaping_roles(p, is_param=True, report_at=report_at)
            self._stamp_escaping_roles(t.func_return_type, is_param=False,
                                       report_at=report_at)
        elif t.kind == TypeKind.OPTIONAL:
            self._stamp_escaping_roles(t.inner_type, is_param=False, report_at=report_at)
        elif t.kind == TypeKind.TUPLE:
            for e in (t.element_types or []):
                self._stamp_escaping_roles(e, is_param=False, report_at=report_at)
        elif t.kind == TypeKind.ARRAY:
            self._stamp_escaping_roles(t.array_element_type, is_param=False, report_at=report_at)
        elif t.kind in (TypeKind.REFERENCE, TypeKind.POINTER):
            # A reference/pointer PARAMETER is a parameter; its referent is
            # storage that outlives the call, so a closure sitting in it is
            # escaping. Recursing with `is_param=False` is what makes
            # `&var Vector<F>` agree with the by-value `Vector<F>` (DF-216e).
            self._stamp_escaping_roles(t.inner_type, is_param=False,
                                       report_at=report_at)
        elif t.kind in (TypeKind.STRUCT, TypeKind.ENUM):
            # design 226: a `FuncPointer<F>`'s argument is NOT a closure-value
            # slot. `escaping` answers "may this closure outlive the frame that
            # built it", and a code address outlives everything — there is no
            # environment for the question to be about. Stamping it anyway put
            # a word in the type's own rendering that the author never wrote
            # and cannot write (`FuncPointer<(Int) sync escaping -> Int>` in
            # every diagnostic), and left two spellings of one type differing
            # in a bit.
            if t.kind == TypeKind.STRUCT and t.struct_name == "FuncPointer":
                return t
            for a in (t.type_args or []):
                self._stamp_escaping_roles(a, is_param=False, report_at=report_at)
        return t

    def _get_underlying_type(self, saw_type: SawType) -> SawType:
        """Get the underlying primitive type for a type (resolves type aliases).
        Used for checking if operations are valid on distinct types."""
        if saw_type.kind == TypeKind.STRUCT and saw_type.struct_name:
            # Resolve type alias to underlying type
            alias_sym = self.get_type_alias_info(saw_type.struct_name)
            if alias_sym:
                return self._get_underlying_type(alias_sym.aliased_type)
        elif saw_type.kind == TypeKind.OPTIONAL and saw_type.inner_type:
            resolved_inner = self._get_underlying_type(saw_type.inner_type)
            return SawType(TypeKind.OPTIONAL, inner_type=resolved_inner)
        return saw_type

    def _alias_ancestor_names(self, saw_type: SawType) -> set:
        """The distinct aliases strictly BELOW `saw_type` on its own chain.

        `type Super = Mid`, `type Mid = Base`, `type Base = Int` gives `Super`
        the set {Mid, Base}. Walks the UNRESOLVED immediate targets, because
        `aliased_type` collapses the chain straight to the underlying and the
        intermediate aliases are exactly what has to stay visible.

        This is what separates an ancestor from a SIBLING (design 63): `Mid` is
        a type `Super` is defined in terms of, so a `Super` is already one;
        `OrderId` merely happens to have the same underlying as `UserId`, and
        being distinct from it is the whole reason both were declared.
        """
        names = set()
        cur = saw_type
        seen = set()
        while (cur is not None and cur.is_struct() and cur.struct_name
               and self.get_type_alias_info(cur.struct_name)
               and cur.struct_name not in seen):
            seen.add(cur.struct_name)
            sym = self.get_type_alias_info(cur.struct_name)
            cur = getattr(sym, 'immediate_type', None)
            if (cur is not None and cur.is_struct()
                    and self.get_type_alias_info(cur.struct_name)):
                names.add(cur.struct_name)
        return names

    def _types_compatible(self, a: Optional[SawType], b: Optional[SawType],
                          allow_literal_to_distinct: bool = False) -> bool:
        """Check if two types are compatible.

        Args:
            a: The source type (what we have)
            b: The target type (what we expect)
            allow_literal_to_distinct: If True, allows primitive types to initialize distinct types.
                                       Only pass True for let/var initialization context.
        """
        if a is None or b is None:
            return True  # Assume compatible if we couldn't determine types

        # A diverging expression has the bottom type NEVER (design 49): it never
        # produces a value, so it is assignable into any expected home.
        if a.kind == TypeKind.NEVER:
            return True

        # None literal is compatible with any optional
        if a.is_none_literal() and b.is_optional():
            return True
        if b.is_none_literal() and a.is_optional():
            return True

        # None literal is compatible with any type that can be wrapped in optional
        # This allows: if cond { value } else { None } to work
        if b.is_none_literal() or a.is_none_literal():
            return True

        # Reference target `&T` / `&var T`: accept a matching reference, or an
        # UnsafePointer<T> (the stdlib bridges a raw payload pointer into a
        # scoped reference closure argument, e.g. Mutex.lock's `body(payload)`).
        # Both lower to a pointer, so this is representation-safe.
        if b.kind == TypeKind.REFERENCE and a.kind in (TypeKind.REFERENCE, TypeKind.POINTER):
            ai, bi = a.inner_type, b.inner_type
            if ai is None or bi is None:
                return True
            if self._types_compatible(ai, bi, allow_literal_to_distinct):
                return True
            return self._type_key(ai) == self._type_key(bi)

        # Allow implicit wrapping: T is compatible with T?
        if b.is_optional() and not a.is_optional():
            if self._types_compatible(a, b.unwrap_optional(), allow_literal_to_distinct):
                return True

        # Allow type alias to implicitly convert to its underlying type
        # e.g., UserId -> Int is allowed, but Int -> UserId is not (except for literals)
        # Also handles chained aliases: SuperInt -> MyInt -> BaseInt -> Int
        if a.is_struct() and self.get_type_alias_info(a.struct_name):
            underlying_a = self._resolve_type_alias(a)
            # When the TARGET is itself a distinct alias, sharing an underlying
            # type is not enough (design 63). An alias satisfies another alias
            # only by being it, or by having it on its own definition chain —
            # `type Super = Mid` makes a `Super` a `Mid`, while `UserId` and
            # `OrderId` over one `Int` are two types that must not mix. This
            # RETURNS rather than falling through: the alias-to-underlying rule
            # below would otherwise re-admit the sibling by way of its
            # underlying, which is the hole this closes.
            if b.is_struct() and self.get_type_alias_info(b.struct_name):
                return (a.struct_name == b.struct_name
                        or b.struct_name in self._alias_ancestor_names(a))
            # Otherwise check if a's underlying type is compatible with b
            if self._types_compatible(underlying_a, b, allow_literal_to_distinct):
                return True

        # Check if b is a distinct type (STRUCT with name in type_aliases)
        if b.is_struct() and self.get_type_alias_info(b.struct_name):
            # Allow primitive types to initialize distinct type wrappers
            # Only in initialization context (allow_literal_to_distinct=True)
            if allow_literal_to_distinct:
                underlying = self._get_underlying_type(b)
                if a.is_primitive():
                    if a.kind == underlying.kind:
                        return True
                    # Also handle distinct optional types: OptInt = Int?
                    # Allow Int to be implicitly wrapped into OptInt
                    if underlying.is_optional() and underlying.inner_type:
                        if a.kind == underlying.inner_type.kind:
                            return True
            # Always allow if 'a' is the same distinct type
            if a.is_struct() and a.struct_name == b.struct_name:
                return True

        # Integer compatibility. A platform `Int`/`UInt` (which is also the type
        # of an UNSUFFIXED integer literal) coerces to/from any integer type —
        # this enables `let x: Int8 = 42`. But two DISTINCT fixed-width kinds do
        # NOT implicitly convert (design 53): a suffixed literal `5u16` assigned
        # to an `Int8` is a type error; explicit `as` is required. Same-kind is
        # always compatible.
        platform_int = {TypeKind.INT, TypeKind.UINT}
        fixed_int = {TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
                     TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64}
        int_kinds = platform_int | fixed_int
        if a.kind in int_kinds and b.kind in int_kinds:
            if a.kind in platform_int or b.kind in platform_int or a.kind == b.kind:
                return True
            return False

        # Allow String to be passed where UnsafePointer<Int8> is expected (for FFI)
        # Saw strings are null-terminated C strings internally
        if (a.kind == TypeKind.STRING and
            b.kind == TypeKind.POINTER and
            b.inner_type and b.inner_type.kind == TypeKind.INT8):
            return True

        # Handle generic enums which can be parsed as STRUCT but typed as ENUM
        # (Parser creates GenericEnum<T> as STRUCT, typechecker returns ENUM)
        a_name = a.enum_name if a.kind == TypeKind.ENUM else (a.struct_name if a.kind == TypeKind.STRUCT else None)
        b_name = b.enum_name if b.kind == TypeKind.ENUM else (b.struct_name if b.kind == TypeKind.STRUCT else None)
        if a_name and b_name and a_name == b_name:
            # Same named type - check if it's an enum and compare type arguments
            if self.namespace.has_enum(a_name):
                a_args = a.type_args or []
                b_args = b.type_args or []
                if len(a_args) != len(b_args):
                    return False
                if len(a_args) == 0:
                    return True  # Non-generic enum, names match
                return all(self._types_compatible(at, bt)
                          for at, bt in zip(a_args, b_args))

        if a.kind != b.kind:
            return False

        # Fixed arrays compare by ELEMENT and LENGTH (design 148). This arm did
        # not exist: array types fell through to the permissive tail below, so
        # `[Int; 3]` and `[Int; 5]` — and `[Int; 3]` and `[String; 3]` — compared
        # as compatible, and a wrong-length argument or field was accepted in
        # silence. A length only one side knows (the abstract half of a generic
        # body, where `[UInt8; N]` has no number yet) is not a mismatch; it is
        # decided per instantiation, where both sides have one.
        if a.kind == TypeKind.ARRAY:
            if not self._types_compatible(a.array_element_type,
                                          b.array_element_type):
                return False
            if a.array_size is None or b.array_size is None:
                return True
            return a.array_size == b.array_size

        # A const generic VALUE argument matches by value.
        if a.kind == TypeKind.CONST_VALUE:
            if a.const_value is None or b.const_value is None:
                return True
            return a.const_value == b.const_value

        # For tuple types, check element types match
        if a.is_tuple():
            if a.element_types is None or b.element_types is None:
                return True
            if len(a.element_types) != len(b.element_types):
                return False
            if not all(self._types_compatible(at, bt)
                       for at, bt in zip(a.element_types, b.element_types)):
                return False
            # Named-tuple label rule (design 63): a named and a POSITIONAL tuple
            # of the same shape are mutually compatible (labels are a view over
            # the positional layout). Two NAMED tuples must agree on names AND
            # order; a mismatch (different names, or a reorder) is incompatible.
            an = a.tuple_field_names
            bn = b.tuple_field_names
            if an is not None and bn is not None:
                return list(an) == list(bn)
            return True

        # For struct types, check struct names match
        if a.is_struct():
            if a.struct_name == b.struct_name:
                # Same named struct — when BOTH sides carry type arguments they
                # must match. This is the D4 cross-heap-unrepresentable property
                # (design 37): a `Vector<Int, LoudAlloc>` is NOT compatible with
                # a `Vector<Int>` (= `Vector<Int, Global>`) because the allocator
                # type parameter differs. Both operands are default-filled here
                # (the comparison chokepoint), so a site that supplied a raw
                # `Vector<Int>` — an unresolved field/return annotation — still
                # compares equal to a resolved `Vector<Int, Global>` value: the
                # canonical identity holds regardless of which paths ran. A bare
                # named type on either side (a trait's `Self` resolved to the
                # plain struct name, or an abstract receiver with no applied
                # args) matches any instantiation, preserving conformance/Self.
                #
                # That last rule has to be decided BEFORE the fill, or the fill
                # defeats it: a struct with a defaulted parameter turns a
                # genuinely bare `Box2` into `Box2<Int>`, which then fails
                # against the abstract `Box2<T>` an extension body produces. The
                # symptom was that an `init` in a generic extension could not
                # name its own type — "method `init` should return `Box2` but
                # returns `Box2<T>`" — for every generic with a default, const
                # (design 148) or type (design 37).
                if not a.type_args or not b.type_args:
                    return True
                a_args = self._append_default_type_args(a.struct_name, a.type_args or [])
                b_args = self._append_default_type_args(b.struct_name, b.type_args or [])
                if a_args and b_args:
                    if len(a_args) != len(b_args):
                        return False
                    return all(self._types_compatible(at, bt)
                               for at, bt in zip(a_args, b_args))
                return True
            # Check if b is a trait that a conforms to
            if self.namespace.has_trait(b.struct_name):
                # a must be a struct that conforms to trait b
                return self.namespace.type_conforms_to(a.struct_name, b.struct_name)
            return False

        # For enum types, check enum names match
        if a.is_enum():
            return a.enum_name == b.enum_name

        # For optional types, check inner types match
        if a.is_optional():
            if a.inner_type is None or b.inner_type is None:
                return True
            return self._types_compatible(a.inner_type, b.inner_type)

        # For function types, check param types and return type match
        if a.is_function():
            a_params = a.param_types or []
            b_params = b.param_types or []
            if len(a_params) != len(b_params):
                return False
            for ap, bp in zip(a_params, b_params):
                if not self._types_compatible(ap, bp):
                    return False
            return self._types_compatible(a.func_return_type, b.func_return_type)

        return True

    def _array_base_kind(self, saw_type: SawType):
        """Peel nested fixed-array layers and return the base element's TypeKind
        (design 33). `[[String; 2]; 3]` -> STRING; a non-array type returns its
        own kind. Used to extend the scalar-String containment exemption to
        arrays of String."""
        node = saw_type
        while node is not None and node.kind == TypeKind.ARRAY:
            node = node.array_element_type
        return node.kind if node is not None else None

    def _is_no_copy_type(self, saw_type: SawType) -> bool:
        """Check if a type is move-only (design 139: its copy tier is 'nocopy').

        Delegates to the shared tier oracle, so a WRAPPER of a move-only value
        answers here too: an `Optional<File>`, a `(File, Int)` tuple, a `[File; 4]`
        array and an enum with a `File` payload are each as move-only as the
        `File` itself. Closures are never move-only (design 73) and a fixed array
        inherits its element's class (design 33); both fall out of the oracle.
        """
        return self.namespace.copy_tier(saw_type) == 'nocopy'

    # ------------------------------------------------------- design 188 (unit 4)
    # `NoMove`: the relocation axis.

    def _is_no_move_type(self, saw_type: SawType, depth: int = 0) -> bool:
        """Whether `saw_type` is PINNED — declared `NoMove`, or a wrapper of one.

        Duplication and relocation are separate axes, so this is deliberately
        not part of `copy_tier`: a NoMove type has a copy tier too (a declared
        `NoCopy`, which the declaration check enforces). Wrappers follow design
        139's rule — an `Optional<TaskGroup>`, a tuple holding one and a
        `[TaskGroup; 4]` are each as unmovable as the group itself.
        """
        if saw_type is None or depth > 12:
            return False
        kind = saw_type.kind
        if kind == TypeKind.OPTIONAL:
            return self._is_no_move_type(saw_type.inner_type, depth + 1)
        if kind == TypeKind.ARRAY:
            return self._is_no_move_type(saw_type.array_element_type, depth + 1)
        if kind == TypeKind.TUPLE:
            return any(self._is_no_move_type(e, depth + 1)
                       for e in (saw_type.element_types or []))
        name = None
        if kind == TypeKind.STRUCT:
            name = saw_type.struct_name
        elif kind == TypeKind.ENUM:
            name = saw_type.enum_name
        if name is None:
            return False
        if self.namespace.type_conforms_to(
                self._canonical_type_name(name), "NoMove"):
            return True
        # design 219 wave C (DF-217j): the containment cascade, DERIVED per
        # INSTANCE. `_check_no_move_declarations` makes a CONCRETE container
        # declare the cascade, and that is the right rule for a type that has a
        # declaration site to add it at. A generic one does not: `Wrap<T>`
        # cannot say `NoMove` — that would pin `Wrap<Int>` too — so its template
        # passed the declaration check with a `T` field and `Wrap<TaskGroup>`
        # relocated a live group, aborting in `taskgroup.saw` (S1 row 4f2).
        #
        # The answer is the one the COPY policy already gives (S1 row 4g): a
        # generic instance's structure is derived from its arguments. So an
        # instantiated container is pinned exactly when a substituted member is
        # — which is design 188's own sentence, "a value that cannot be
        # relocated cannot be relocated inside something else either", applied
        # where no declaration could have carried it.
        if not saw_type.type_args:
            return False
        if name.startswith("__Frame_"):
            # A coroutine frame is constructed, resumed by `&var` and dropped in
            # place — never relocated. Same exemption the declaration check and
            # the NoCopy containment check make (design 62 G1).
            return False
        return any(self._is_no_move_type(member, depth + 1)
                   for member in self._instance_member_types(saw_type))

    def _instance_member_types(self, saw_type: SawType):
        """The member types of an INSTANTIATED generic struct/enum, with its
        type arguments substituted in — the per-instance structure the copy
        tier already derives (`_struct_structural_copy_tier`), reused here so
        the NoMove cascade and the copy policy answer from one model."""
        name = (saw_type.struct_name if saw_type.kind == TypeKind.STRUCT
                else saw_type.enum_name)
        struct_info = self.namespace.structs.get(name)
        enum_info = None if struct_info is not None else self.namespace.enums.get(name)
        info = struct_info or enum_info
        if info is None:
            return []
        type_map = {tp.name: arg for tp, arg in
                    zip(getattr(info, 'type_params', None) or [],
                        saw_type.type_args or [])}
        if not type_map:
            return []
        out = []
        if struct_info is not None:
            for field_type in struct_info.fields.values():
                if field_type is not None:
                    out.append(field_type.substitute(type_map))
        else:
            for payloads in enum_info.variants.values():
                for _pname, ptype in (payloads or []):
                    if ptype is not None:
                        out.append(ptype.substitute(type_map))
        return out

    def _no_move_scope_note(self, saw_type: SawType) -> str:
        """The extra sentence a refused move of a `TaskGroup` earns.

        The rule is design 124's, not design 188's — a group is a scope, and its
        `Deinit` structured-joins its children where the group was born — so the
        diagnostic says so rather than leaving the reader to find out why a type
        they did not declare is pinned.
        """
        name = (saw_type.struct_name if saw_type is not None
                and saw_type.kind == TypeKind.STRUCT else None)
        if name is None or self._canonical_type_name(name) != "TaskGroup":
            return ""
        return (" A `TaskGroup` is a SCOPE (design 124): its `Deinit` "
                "structured-joins its children where the group was born, and "
                "every spawned frame holds the group's address — so a group "
                "that moved would join in one place and be driven from "
                "another. Keep it in the frame that opened it and pass "
                "`&var group` down, or spawn into a group the caller owns.")

    def _is_implicit_copy_type(self, saw_type: SawType) -> bool:
        """Check if a type implements Copy."""
        if saw_type is None:
            return False

        # An escaping closure is a compiler-known Copy value (design 73):
        # copying it retains a refcounted heap env, the last owner's drop tears it
        # down exactly once. A non-escaping closure is a borrow (owns nothing) and
        # is freely forwardable — not a Copy transfer.
        if saw_type.kind == TypeKind.FUNCTION:
            return bool(getattr(saw_type, 'func_is_escaping', False))

        # A fixed array `[T; N]` inherits T's copy class (design 33): it is
        # Copy iff its element type is (per-element implicit copy).
        if saw_type.kind == TypeKind.ARRAY:
            return self._is_implicit_copy_type(saw_type.array_element_type)

        # Get the type name for conformance lookup
        type_name = None
        if saw_type.kind == TypeKind.STRUCT:
            type_name = saw_type.struct_name
        elif saw_type.kind == TypeKind.ENUM:
            type_name = saw_type.enum_name
        elif saw_type.kind == TypeKind.STRING:
            # String is a compiler-known refcounted Copy type.
            type_name = "String"

        if type_name is None:
            return False

        # Check if type declares the silent copy tier (either spelling).
        return self.namespace.declares_copy_tier(type_name)

    def _is_explicit_copy_type(self, saw_type: SawType) -> bool:
        """Check if a type is ExplicitCopy (never implicitly duplicated; a
        transfer is `move`, a duplicate is a visible `.copy()`).

        Delegates to the shared tier oracle (design 139), so an `Optional<Vector<Int>>`
        answers here exactly as the `Vector<Int>` does — that wrapper hole is
        what DF-131a reported.
        """
        return self.namespace.copy_tier(saw_type) == 'explicit'

    def _is_trivially_copyable(self, saw_type: SawType) -> bool:
        """A type is trivially copyable iff it can be duplicated bitwise: all
        fields are trivially copyable, and it declares no resource trait
        (Deinit / NoCopy / Copy / ExplicitCopy). Such types auto-satisfy
        `Copy`; `.copy()` on them lowers to a bitwise copy.

        The structural logic lives on the namespace (`Namespace.is_trivially_copyable`)
        so codegen's bounded-extension gating uses the exact same rule. Here we
        only add the typechecker-local guard: an opaque generic type parameter
        currently in scope is never known to be trivial.
        """
        if (saw_type is not None and saw_type.kind == TypeKind.STRUCT
                and saw_type.struct_name in getattr(self, 'current_type_params', {})):
            return False
        return self.namespace.is_trivially_copyable(saw_type)

    def _type_satisfies_copy_bound(self, saw_type: SawType) -> bool:
        """Whether a concrete type satisfies the merged `Copy` bound: on the
        silently-copyable tier, derived or declared.

        Delegates to the shared namespace helper so codegen agrees.
        """
        return self.namespace.type_satisfies_copy_bound(saw_type)

    def _is_deinit_type(self, saw_type: SawType) -> bool:
        """Check if a type implements Deinit (directly or through NoCopy/Copy/ExplicitCopy)."""
        if saw_type is None:
            return False

        # A fixed array `[T; N]` needs element destruction iff its element type
        # does (design 33).
        if saw_type.kind == TypeKind.ARRAY:
            return self._is_deinit_type(saw_type.array_element_type)

        # Get the type name for conformance lookup
        type_name = None
        if saw_type.kind == TypeKind.STRUCT:
            type_name = saw_type.struct_name
        elif saw_type.kind == TypeKind.ENUM:
            type_name = saw_type.enum_name

        if type_name is None:
            return False

        # Check if type conforms to Deinit, directly or through a copy policy.
        # `NoCopy` and `ExplicitCopy` inherit from Deinit; `Copy` does not name
        # it as a supertrait, so it is asked for explicitly here — the
        # membership is what this predicate means, not the ancestry.
        return (self.namespace.type_conforms_to(type_name, "Deinit") or
                self.namespace.type_conforms_to(type_name, "NoCopy") or
                self.namespace.declares_copy_tier(type_name) or
                self.namespace.type_conforms_to(type_name, "ExplicitCopy"))

    # Expression kinds that read a value out of *existing* owned storage,
    # as opposed to producing a freshly constructed temporary. Transferring
    # one of these leaves a live second owner behind, so these are exactly the
    # sites where NoCopy move-discipline must be enforced and Copy
    # `copy()` must be inserted. A struct/enum init, call result, or literal is
    # a fresh temporary and is *not* aliasing.
    _ALIASING_EXPR_TYPES = (Identifier, MemberAccess, ArrayIndex, TupleIndex)

    def _is_aliasing_expr(self, expr: Expression) -> bool:
        """True if `expr` reads a value out of existing owned storage.

        design 131: a force-unwrap is transparent here. `o!` is a PROJECTION of
        `o` — it names the payload sitting inside storage `o` still owns, exactly
        as `s.field` names storage `s` owns. So `o!` aliases iff `o` does: a
        payload read out of a local/field/element is a place, while `f()!` (the
        payload of a fresh temporary the caller already owns) is not.
        """
        if isinstance(expr, ForceUnwrap):
            return self._is_aliasing_expr(expr.expr)
        # design 139: `Slot.Empty` is a payload-free enum variant LITERAL. It
        # wears the same node type as `config.slot`, but it constructs a fresh
        # value out of nothing rather than naming storage somebody else owns, so
        # it is no more aliasing than `Slot.Occupied(r: R(id: 7))` beside it.
        # Only the typechecker can tell the two spellings apart, which is why
        # this rides an annotation instead of a node type.
        if getattr(expr, 'enum_variant_literal', False):
            return False
        return isinstance(expr, self._ALIASING_EXPR_TYPES)

    # ------------------------------------------------------------------
    # design 131 — the policy-driven place rule for optional payload reads.
    #
    # Every payload-extraction form (`o!`, the `??` left operand, an
    # `if let`/`guard let` binding) reads out of storage the source keeps. The
    # Copy family decides what that read costs, using the SAME table as every
    # other read: trivial payloads copy bitwise, Copy retains, and
    # ExplicitCopy/NoCopy refuse and name the three consuming spellings.
    # ------------------------------------------------------------------

    def _payload_read_policy(self, payload_type: Optional[SawType]) -> str:
        """The copy tier a payload read must honor: one of
        'trivial' / 'retain' / 'explicit' / 'nocopy'.

        One line, because the answer belongs to ONE oracle
        (`Namespace.read_policy` over `copy_tier`, design 193 unit 1). This used
        to re-derive the table out of three predicates and a type-parameter
        carve-out of its own, and the three derivations did not agree — a
        non-escaping closure payload was 'retain' here and 'free' there.
        """
        if payload_type is None:
            return 'trivial'
        # A type parameter in scope reads as an opaque STRUCT name; `copy_tier`
        # calls that 'abstract', which the shared table maps to the same
        # bitwise read this carve-out always gave it.
        if (payload_type.kind == TypeKind.STRUCT
                and payload_type.struct_name in getattr(self, 'current_type_params', {})):
            return 'trivial'
        return self.namespace.read_policy(payload_type)

    def _check_payload_read(self, source: Optional[Expression],
                            payload_type: Optional[SawType],
                            node, context: str, line: int, column: int):
        """The value-read row for a payload extracted from `source`.

        `source` is the optional being read (the `if let` scrutinee, the `??`
        left operand); `node` is the AST node codegen will consult. A `move`
        source or a fresh temporary is already owned by the reader, so only a
        PLACE source is checked.

        THE MARK IS ASSIGNED HERE, NOT ACCUMULATED (design 218 stage 1). This
        is the only place `payload_needs_copy` is stamped, and the front half
        runs more than once over one AST — so a pass that decides "no retain"
        has to say so, or the previous pass's answer stands. It used to be safe
        to just return, because the SOURCE never changed between passes; the
        coroutine transform now rewrites a frame local into a `Slot.value()`
        lend, which turns a plain local read into a place read (and, after the
        place lowering, into an owned window temporary) — three different
        answers for one node, of which only the last is right. The frame-read
        case below is the deliberate exception, and says why.
        """
        if (getattr(node, 'frame_place_read', False)
                or getattr(source, 'frame_place_read', False)):
            # A coroutine-frame field read on a LEGACY encoding carries the
            # transform's own ownership bookkeeping: a `move` read hands the
            # frame's reference over through `__saw_forget`, a non-`move` read
            # is retained by codegen's frame-read path (design 124), and a
            # `self_opt` field IS the optional, drop flag and all. The transform
            # runs AFTER the type-check that already judged these reads in their
            # original, un-projected form, and the whole program is then
            # re-checked — so weighing in here would judge one read twice: a
            # Copy payload would be retained a second time (a leak), and a
            # NoCopy payload the frame is legitimately moving out would be
            # rejected. The first pass's answer is the answer, so it is left
            # exactly as it stands. (The mark rides the unwrap for a `o!` value
            # read and the SOURCE for an `if let` / `??` over a frame field.)
            return
        if source is None or not self._is_aliasing_expr(source):
            node.payload_needs_copy = False
            return
        # A `borrows` accessor's result is judged by the PLACE rule instead
        # (`place_uses._value_read_ok`), which knows the element type, the
        # receiver and which escape hatches that receiver actually publishes.
        # Both rules firing on one read is not a stricter check but a WRONG one:
        # `m["k"]` carries `place_struct` and is an `ArrayIndex`, so an
        # Copy value got `payload_needs_copy` here AND `place_value_read`
        # there, and `let held = m["k"]!` retained twice against one release.
        # `v.get(i)!` never had the problem only because a MethodCall is not in
        # the aliasing set; the subscript spelling made the overlap reachable.
        #
        # CLEARED, not merely skipped (design 218 stage 1). The coroutine
        # transform rewrites a frame local into a `Slot.value()` lend, so a
        # source that was a plain local on the FIRST check is a place on the
        # second — and the mark the first check left is exactly the double
        # retain the paragraph above forbids, one pass later. The place rule is
        # the authority for a place source at every pass, so it takes the mark
        # away as well as declining to add one.
        if self._reads_a_place(source):
            node.payload_needs_copy = False
            return
        policy = self._payload_read_policy(payload_type)
        node.payload_needs_copy = (policy == 'retain')
        if policy == 'nocopy':
            # One policy, two refusals: the tier says "not silently duplicable",
            # and the CONFORMANCE says whether `.copy()` is among the ways out
            # (design 219 — the tier no longer carries that second answer).
            duplicable = self._is_explicit_copy_type(payload_type)
            self._error(
                ErrorKind.CANNOT_COPY,
                f"cannot read the payload out of `{self._render_place(source)}` "
                f"in {context}: `{payload_type}` implements "
                f"{'ExplicitCopy' if duplicable else 'NoCopy'}",
                line, column,
                hint=self._payload_read_hint(source, duplicable)
            )

    def _reads_a_place(self, expr: Expression) -> bool:
        """Does this source name a `borrows` accessor's place?

        Transparent through `!` for the same reason `_is_aliasing_expr` is:
        `m["k"]!` is a projection of the place `m["k"]`.
        """
        if isinstance(expr, ForceUnwrap):
            return self._reads_a_place(expr.expr)
        return getattr(expr, 'place_struct', None) is not None

    def _render_place(self, expr: Expression) -> str:
        """A source-shaped rendering of a place expression, for diagnostics."""
        if isinstance(expr, ForceUnwrap):
            return self._render_place(expr.expr) + "!"
        try:
            return self._render_lvalue_path(expr)
        except Exception:
            return "the optional"

    def _payload_read_hint(self, source: Expression, duplicable: bool) -> str:
        """The consuming spellings a refused payload read can be rewritten to.

        `duplicable` is whether the payload has an `ExplicitCopy` conformance,
        which is what puts `.copy()` among the ways out (design 219).
        """
        path = self._render_place(source)
        parts = []
        if duplicable:
            parts.append(f"`{path}!.copy()` for an explicit deep copy")
        if isinstance(source, Identifier):
            parts.append(f"`move {path}!` to transfer the whole binding")
        parts.append(f"`{path}.take()` to move the payload out in place")
        return "use " + ", ".join(parts[:-1]) + (", or " if len(parts) > 1 else "") + parts[-1]

    # ------------------------------------------------------------------
    # Per-function, scope-aware may-move state (design 15).
    #
    # State is a dict keyed by VariableInfo.binding_id -> (var_info, name, line, col).
    # The binding's VariableInfo is its identity: same-named bindings in
    # different functions or shadowing scopes are distinct objects, so they
    # never interact (the flat-set bug from brief 03). A snapshot is a plain
    # dict copy; branch merges union the surviving branch end-states.
    # ------------------------------------------------------------------

    def _binding_move_info(self, var_info):
        """Return (name, line, col) if this binding is moved-from, else None."""
        entry = self.moved_bindings.get(var_info.binding_id)
        if entry is None:
            return None
        _, name, line, col, _prov = entry
        return name, line, col

    def _binding_move_is_provisional(self, var_info) -> bool:
        """Whether the recorded move is a design-219 PROVISIONAL one — a
        transfer of an abstract-tier value, which the dataflow is still
        deciding between a move and a duplicate. A use of one is not a
        use-after-move error; it is the evidence that raises the type
        parameter's requirement (see `typechecker/tierreq.py`)."""
        entry = self.moved_bindings.get(var_info.binding_id)
        return bool(entry is not None and entry[4])

    def _is_binding_moved(self, var_info) -> bool:
        return var_info.binding_id in self.moved_bindings

    def _mark_binding_moved(self, var_info, name: str, line: int, column: int,
                            provisional: bool = False):
        self.moved_bindings[var_info.binding_id] = (var_info, name, line,
                                                    column, provisional)

    def _revive_binding(self, var_info):
        """Clear moved-state for a binding (revival by assignment)."""
        self.moved_bindings.pop(var_info.binding_id, None)

    def _snapshot_moves(self) -> dict:
        return dict(self.moved_bindings)

    def _merge_move_branches(self, entry: dict, branches: list) -> dict:
        """Union-merge branch end-states, excluding diverged branches.

        `branches` is a list of (end_state_dict, diverges_bool). A binding is
        may-moved after the construct if ANY non-diverging branch left it moved.
        If every branch diverges (code after is unreachable), fall back to the
        pre-construct entry state.
        """
        contributing = [st for st, diverges in branches if not diverges]
        if not contributing:
            return dict(entry)
        merged: dict = {}
        for st in contributing:
            merged.update(st)
        return merged

    # ------------------------------------------------------------------
    # Operand agreement (design 195 rule 1).
    # ------------------------------------------------------------------

    # The integer kinds the operand-agreement rule quantifies over.
    _AGREEMENT_INT_KINDS = frozenset({
        TypeKind.INT, TypeKind.UINT,
        TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
        TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64,
    })

    # The `T` half of each design-170 conversion spelling, keyed by kind, for the
    # hint. Platform `Int`/`UInt` are in here too: `x as UInt` is a written
    # conversion exactly as `x as UInt8` is.
    _AGREEMENT_TYPE_NAMES = {
        TypeKind.INT: 'Int', TypeKind.UINT: 'UInt',
        TypeKind.INT8: 'Int8', TypeKind.INT16: 'Int16',
        TypeKind.INT32: 'Int32', TypeKind.INT64: 'Int64',
        TypeKind.UINT8: 'UInt8', TypeKind.UINT16: 'UInt16',
        TypeKind.UINT32: 'UInt32', TypeKind.UINT64: 'UInt64',
    }

    @staticmethod
    def _bare_int_literal(expr) -> Optional[IntLiteral]:
        """The BARE (unsuffixed) integer literal inside `expr`, or None.

        Rule 1's one carve-out. A bare literal has no width of its own and adopts
        whatever slot it lands in (design 87); a SUFFIXED literal is exact-typed
        (design 53) and is a typed operand like any other.

        A NEGATED bare literal is one too — the leading `-` is not a suffix, and
        `_apply_literal_expected_type` has treated `-5` as an adopting literal at
        every other slot since design 87. Missing that here is what made
        `n * -2` on an `Int16 n` an internal compiler error while `n * 2` beside
        it worked.
        """
        from ast_nodes import UnaryOp
        inner = expr
        if isinstance(inner, UnaryOp) and inner.op == '-':
            inner = inner.operand
        if isinstance(inner, IntLiteral) and getattr(inner, 'suffix', None) is None:
            return inner
        return None

    def _check_operand_agreement(self, left_expr, right_expr,
                                 left_type: Optional[SawType],
                                 right_type: Optional[SawType],
                                 subject: str, line: int, column: int,
                                 left_label: str = "left",
                                 right_label: str = "right") -> bool:
        """THE operand-agreement funnel — design 195 rule 1.

        ALL TYPED OPERANDS OF AN OPERATION HAVE THE SAME TYPE. Implicit promotion
        happens from BARE integer literals and nowhere else: a literal adopts the
        other operand's type, a suffixed literal is exact-typed, and a named value
        carries the type it was declared with. There is no promotion ladder — an
        operation has two peers, and picking a winner between them is policy Saw
        does not adopt. Mixed WIDTH and mixed SIGNEDNESS are the same error, and
        so is a `Float` beside an integer.

        ENTRY POINTS — every position an operation takes two numeric peers:

        - ``_check_binary_op``, arithmetic ``+ - * /`` and ``%``
        - ``_check_binary_op``, the wrapping trio ``&+ &- &*``
        - ``_check_binary_op``, the bitwise ``& | ^``
        - ``_check_binary_op``, the comparisons ``== != < > <= >=``
        - ``_check_compound_assign_statement``, ``+= -= *= /= %= &= |= ^=``
        - ``_check_range_expr``, a range's two bounds

        NOT an entry point, deliberately: the SHIFTS ``<< >>`` and their compound
        forms. A shift's right operand is a COUNT, not a peer — it is range-checked
        against the left operand's width at runtime and contributes nothing to the
        result's type — so a count of a different width stays legal (design 195
        matrix row 6, the documented exemption).

        Returns True when the operands agree, one of them adopts, or the pair is
        not two numeric peers; False when it reported.
        """
        if left_type is None or right_type is None:
            return True
        lu = self._get_underlying_type(left_type)
        ru = self._get_underlying_type(right_type)
        numeric = self._AGREEMENT_INT_KINDS | {TypeKind.FLOAT}
        if lu.kind not in numeric or ru.kind not in numeric:
            # Not two numeric peers (a String comparison, pointer arithmetic, a
            # generic type parameter). The operator's own arm owns those.
            return True
        if lu.kind == ru.kind:
            return True
        # The carve-out is integer-only. A bare INTEGER literal beside a `Float`
        # does not adopt: whether an integer literal may become a float one is a
        # language question design 195 did not take (DF-195d), so the mix is
        # refused with a hint naming the float spelling.
        if (lu.kind != TypeKind.FLOAT and ru.kind != TypeKind.FLOAT
                and (self._bare_int_literal(left_expr) is not None
                     or self._bare_int_literal(right_expr) is not None)):
            return True
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"{subject} requires both operands to have the same type, but the "
            f"{left_label} is `{left_type}` and the {right_label} is `{right_type}`",
            line, column,
            hint=self._operand_agreement_hint(left_expr, right_expr, lu, ru)
        )
        return False

    def _operand_agreement_hint(self, left_expr, right_expr,
                                lu: SawType, ru: SawType) -> str:
        """The ways out of a refused operand pair, chosen by what was written.

        Two outs in the general case (design 195's ruling): write the conversion,
        or drop a suffix so the literal adopts. The second only exists when one
        operand IS a suffixed literal, so it is offered only there — an author
        with two named values has no suffix to drop and should not be sent looking
        for one.
        """
        if lu.kind == TypeKind.FLOAT or ru.kind == TypeKind.FLOAT:
            return ("`Float` and the integer types never convert implicitly — "
                    "write a float literal (`1.0`), or convert the operand "
                    "explicitly")
        suffixed = None
        other = None
        for expr, other_kind in ((left_expr, ru.kind), (right_expr, lu.kind)):
            if (isinstance(expr, IntLiteral)
                    and getattr(expr, 'suffix', None) is not None):
                suffixed = expr.suffix
                other = self._AGREEMENT_TYPE_NAMES.get(other_kind)
                break
        target = self._AGREEMENT_TYPE_NAMES.get(lu.kind, 'the other type')
        convert = (f"convert one operand — `x as {target}` panics out of range, "
                   f"`{target}.from(x)` answers `None`, "
                   f"`{target}.from(truncating: x)` keeps the low bits")
        if suffixed is not None and other is not None:
            return (f"drop the `{suffixed}` suffix so the literal adopts "
                    f"`{other}`, or {convert}")
        return convert

    def _adopt_bare_literal_operand(self, expr, left_type: Optional[SawType],
                                    right_type: Optional[SawType]) -> Optional[SawType]:
        """Rule 1's carve-out, applied: a BARE integer literal operand adopts the
        other operand's type, and the operation answers in that type.

        The literal is stamped through `_apply_literal_expected_type`, the same
        expected-type propagation every other slot uses (design 87), so it is
        range-checked AT the literal, materialized at the adopted width, and — the
        part the old fixed-width-only version missed — reached through a leading
        `-`. Adoption covers PLATFORM types too, not just `Int8`..`UInt64`: a
        literal beside a `UInt` is a `UInt`, which is what makes `1 / u` an
        unsigned division rather than a signed one over unsigned bits.

        Returns the adopted type, or None when neither operand is a bare literal
        beside a typed integer (two bare literals included — neither has a type to
        adopt from, so both stay platform `Int`).
        """
        if left_type is None or right_type is None:
            return None
        left_lit = self._bare_int_literal(expr.left) is not None
        right_lit = self._bare_int_literal(expr.right) is not None
        if left_lit and right_lit:
            return None
        if right_lit:
            return self._adopt_bare_literal_into(expr.right, left_type)
        if left_lit:
            return self._adopt_bare_literal_into(expr.left, right_type)
        return None

    def _adopt_bare_literal_into(self, value_expr,
                                 target: Optional[SawType]) -> Optional[SawType]:
        """Make a BARE integer literal adopt `target`, and answer with `target`.

        The one implementation of rule 1's carve-out. `_adopt_bare_literal_operand`
        calls it for a `BinaryOp`'s two operands; `_check_nil_coalesce` calls it
        for the `??` default beside its payload, which is the same two-peer
        question written without a `BinaryOp`.

        It stamps through `_apply_literal_expected_type` — the design-87 propagation
        every other slot uses, so the literal is range-checked AT the literal,
        materialized at the adopted width, and reached through a leading `-` — and
        then pins `resolved_type` itself. That last step is not redundant:
        `visit_IntLiteral` honors only a FIXED-width expectation, so a platform
        `UInt` target would fall back to `Int` and leave the operation reading
        unsigned bits through signed instructions.

        Returns None when the rule does not apply: a non-literal, a non-integer
        target, or a CONST position — where `const_eval` folds the whole
        expression in the signed platform-`Int` domain whatever the operand types
        say (design 185: `~0` is `-1` there, and `~Perm.Read` is `-2` even though
        the flag reading types it `UInt8`), so pinning a literal to an operand's
        width would range-check it against a width the fold does not use.
        Agreement still runs in a const position — the funnel's carve-out admits a
        bare literal on its own.
        """
        if value_expr is None or target is None:
            return None
        if self._in_const_position():
            return None
        rt = self._get_underlying_type(target)
        if rt.kind not in self._AGREEMENT_INT_KINDS:
            return None
        if self._bare_int_literal(value_expr) is None:
            return None
        self._apply_literal_expected_type(value_expr, target)
        value_expr.resolved_type = SawType(rt.kind)
        return target

    # ------------------------------------------------------------------
    # Value-branch merging (design 195 rule 2).
    # ------------------------------------------------------------------

    _AGREEMENT_UNSIGNED_KINDS = frozenset({
        TypeKind.UINT, TypeKind.UINT8, TypeKind.UINT16,
        TypeKind.UINT32, TypeKind.UINT64,
    })

    _AGREEMENT_FIXED_WIDTHS = {
        TypeKind.INT8: 8, TypeKind.INT16: 16,
        TypeKind.INT32: 32, TypeKind.INT64: 64,
        TypeKind.UINT8: 8, TypeKind.UINT16: 16,
        TypeKind.UINT32: 32, TypeKind.UINT64: 64,
    }

    def _int_kind_width(self, kind) -> Optional[int]:
        """The bit width of an integer kind at the EFFECTIVE target.

        Platform `Int`/`UInt` are POINTER-WIDTH (design 47), so `Int64` widens
        into `Int` on a 64-bit target and NARROWS into it on riscv32. Reading the
        width off the target rather than assuming 64 is what keeps the merge below
        answering per profile.
        """
        w = self._AGREEMENT_FIXED_WIDTHS.get(kind)
        if w is not None:
            return w
        if kind in (TypeKind.INT, TypeKind.UINT):
            return getattr(self, 'platform_int_width', 64)
        return None

    def _int_widens_losslessly(self, src, dst) -> bool:
        """Whether every value of integer kind `src` has a `dst` value.

        LANGUAGE_SPEC's conversion cost table exactly: the identity, same-sign
        widening, and unsigned into STRICTLY wider signed. Everything else is a
        narrowing or a sign change at or above the source width — a value the
        target cannot represent, which is why design 170 makes those a WRITTEN
        conversion.
        """
        if src == dst:
            return True
        sw = self._int_kind_width(src)
        dw = self._int_kind_width(dst)
        if sw is None or dw is None:
            return False
        s_unsigned = src in self._AGREEMENT_UNSIGNED_KINDS
        d_unsigned = dst in self._AGREEMENT_UNSIGNED_KINDS
        if s_unsigned == d_unsigned:
            return sw <= dw
        if s_unsigned:
            return sw < dw
        return False

    def _merge_value_branch_types(self, arm_types, subject: str,
                                  line: int, column: int) -> Optional[SawType]:
        """THE value-branch merge — design 195 rule 2.

        Each arm of a value `if`/`match`, and each operand of `??`, hands its
        value to ONE merged home, so each is a TRANSFER and takes the rule a
        `return` takes: a lossless widening is free, and anything else is the
        ordinary transfer error. The merged type is the arm type every other arm
        widens into losslessly.

        ENTRY POINTS:

        - ``_check_if_expr`` — the then and else branch values
        - ``_reconcile_match_arm_types`` — every arm of a value `match`, on both
          the enum-switch path and the general pattern path
        - ``_check_nil_coalesce`` — the `??` payload beside its default

        `arm_types` is the arms' types in ARM ORDER; an arm that yields no value
        (a diverging `panic`, a block whose every path returned) is the caller's
        to filter out. Returns None when the arms are not ALL integers — every
        other merge in the language, and none of this rule's business — and ALSO
        when they already agree, so a merge that has nothing to do leaves the
        caller's own answer and its lowering byte-identical.

        When two arm types each widen into the other (two same-width, same-sign
        kinds, e.g. `Int` and `Int64` on a 64-bit target) the FIRST in arm order
        wins, so the answer does not depend on which arm was written first
        producing a different lowering on a re-run.
        """
        if not arm_types:
            return None
        kinds = []
        for t in arm_types:
            if t is None:
                return None
            rt = self._get_underlying_type(t)
            if rt.kind not in self._AGREEMENT_INT_KINDS:
                return None
            kinds.append(rt.kind)
        if len(set(kinds)) <= 1:
            return None
        for i, candidate in enumerate(kinds):
            if all(self._int_widens_losslessly(k, candidate) for k in kinds):
                return arm_types[i]
        seen = []
        for t in arm_types:
            rendered = f"`{t}`"
            if rendered not in seen:
                seen.append(rendered)
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"{subject} have no common type: {' and '.join(seen)} — neither "
            f"widens into the other without losing a value",
            line, column,
            hint="a narrowing or a same-width sign change has to be written: "
                 "`x as T` panics out of range, `T.from(x)` answers `None`, "
                 "`T.from(truncating: x)` keeps the low bits"
        )
        return arm_types[0]

    def _widened(self, value_expr, merged: Optional[SawType]):
        """`value_expr` extended to `merged`, or unchanged (design 195 rule 2).

        The widening is a SYNTHESIZED `as`. Design 170's cast lowering already
        extends by the SOURCE's signedness — which is what preserves the value —
        and stamps no runtime check on a total pair, so building the node the
        author could have written keeps ONE integer-conversion lowering in the
        compiler instead of a second one at each branch merge. It is also
        idempotent: the wrapped arm types as `merged` on the design-146 second
        pass, so the merge finds the arms already equal and wraps nothing more.
        """
        from ast_nodes import CastExpr
        if value_expr is None or merged is None:
            return value_expr
        t = getattr(value_expr, 'resolved_type', None)
        if t is None:
            return value_expr
        if self._get_underlying_type(t).kind == self._get_underlying_type(merged).kind:
            return value_expr
        cast = CastExpr(expr=value_expr, target_type=merged,
                        line=getattr(value_expr, 'line', 0),
                        column=getattr(value_expr, 'column', 0))
        cast.resolved_type = merged
        return cast

    def _check_value_transfer(self, expr: Optional[Expression], target_type: Optional[SawType],
                              context: str, line: int, column: int,
                              is_return: bool = False):
        """Single checkpoint every copy/move site funnels through.

        Every site where a value is copied or moved into a new home (let/var
        initializers, assignment RHS, call arguments, returns, struct-field
        initializers, array/tuple elements, enum payloads) routes through here.
        It enforces NoCopy move-discipline and marks Copy sites so codegen
        inserts `copy()` uniformly.

        Behavior by the source expression and its resolved type:
        - `move x`: ownership transfers; a transfer is neither a copy nor a
          NoCopy violation, so it is always accepted. The source binding's
          moved-from state is recorded in `_check_move_expr` (design 15), which
          runs for every `move` regardless of the enclosing transfer site.
        - by-reference argument (`&x` / `&var x`): NOT a transfer; skipped.
        - NoCopy type read from an existing binding (identifier / field access /
          index): an error -- it must be `move`d. A fresh temporary is fine.
        - Copy type read from an existing binding: annotated
          `expr.needs_copy = True` for codegen. A fresh temporary is fine.
        - anything else: no-op.
        """
        if expr is None:
            return

        # design 24 item 3 (the `sync` boundary): a `sync` function type accepts
        # only a `sync` value. A closure LITERAL is exempt — it is effect-checked
        # in the sync context it is passed into (`_effect_enter_closure` reads the
        # expected type's `sync` flag). Any OTHER function value (a stored or
        # forwarded function, a non-`sync` function-typed field) is rejected at
        # the boundary unless its own type is `sync`, because it could suspend and
        # a `sync` context must be transitively suspension-free.
        if (target_type is not None and target_type.kind == TypeKind.FUNCTION
                and getattr(target_type, 'func_is_sync', False)
                and not isinstance(expr, ClosureExpr)):
            src = getattr(expr, 'resolved_type', None)
            if (src is not None and src.kind == TypeKind.FUNCTION
                    and not getattr(src, 'func_is_sync', False)):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot pass a non-`sync` function value where a `{target_type}` "
                    f"is expected",
                    line, column,
                    hint="pass a `sync`-typed function value or a closure literal "
                         "that is checked suspension-free"
                )

        # There is no `unsafe` variance gate on function values. Design 136 makes
        # the effect a property of the SIGNATURE — a value and the slot it flows
        # into agree on it whenever their signatures agree, and a signature
        # mismatch is an ordinary type error. Design 130's gate compared a
        # body-derived bit against a written one, which is the pair of spellings
        # that no longer exists.

        # design 16/29 escaping variance: a non-escaping function VALUE may not
        # flow into an escaping slot. non-escaping <: escaping (the SAFE
        # direction is escaping-value → non-escaping-slot: the callee promises
        # not to store it). The error direction is non-escaping-value → escaping
        # slot: the callee may store a value whose captures borrow a frame that
        # will die. A closure LITERAL is exempt — it is lowered to match the slot
        # (an escaping heap env when the target is escaping); only a stored/
        # forwarded function value (e.g. a non-escaping closure PARAM) is gated.
        # The target's escaping bit is set at its declaration site: closure
        # parameters default non-escaping, every other role (field, return,
        # binding) is stamped escaping by `_stamp_escaping_roles`.
        if (target_type is not None and target_type.kind == TypeKind.FUNCTION
                and getattr(target_type, 'func_is_escaping', False)
                and not isinstance(expr, ClosureExpr)):
            src = getattr(expr, 'resolved_type', None)
            if (src is not None and src.kind == TypeKind.FUNCTION
                    and not getattr(src, 'func_is_escaping', False)):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot store or forward a non-escaping closure into an "
                    f"escaping `{target_type}` slot ({context})",
                    line, column,
                    hint="a non-escaping closure's captures may borrow the "
                         "enclosing frame; only call it or pass it as another "
                         "non-escaping argument"
                )

        # `move x` transfers ownership; a move is never a copy/NoCopy violation.
        # Moved-from recording happens in `_check_move_expr` (design 15).
        if isinstance(expr, MoveExpr):
            return

        # `&x` / `&var x` bind to a by-reference parameter; the callee mutates
        # the caller's value in place -- no transfer, no copy.
        if isinstance(expr, ReferenceExpr):
            return

        src_type = getattr(expr, 'resolved_type', None) or target_type
        if src_type is None:
            return

        # An escaping closure forwarded into a NON-escaping (borrowing) slot is a
        # LEND, not an ownership transfer (design 71 / design 16/29 variance): the
        # callee promises not to store it, so the caller keeps ownership and drops
        # it once. No retain, no move — the borrowing param owns nothing and never
        # drops it. Stamp `closure_lend` so codegen does NOT clear the source's
        # drop flag (the default for a non-copied Identifier transfer); without
        # this the caller's env would leak (never dropped) — a pre-existing bug the
        # Copy model surfaces (design 73).
        if (src_type.kind == TypeKind.FUNCTION
                and getattr(src_type, 'func_is_escaping', False)
                and target_type is not None
                and target_type.kind == TypeKind.FUNCTION
                and not getattr(target_type, 'func_is_escaping', False)):
            if isinstance(expr, (Identifier, MemberAccess, ArrayIndex, TupleIndex)):
                expr.closure_lend = True
            return

        # design 131: `o!` in a value position is a payload read out of storage
        # `o` still owns. Route it to the shared place rule, which applies the
        # same four-tier table with the hints that fit a projection (`o!.copy()`
        # / `move o!` / `o.take()`) — and marks the RETAIN on the unwrap node,
        # where codegen performs it, rather than on the transfer site (a `let`
        # initializer never reaches the transfer-site copy path).
        if isinstance(expr, ForceUnwrap):
            self._check_payload_read(expr.expr, src_type, expr, context,
                                     line, column)
            return

        # design 131/139: a read the coroutine transform synthesized out of a
        # frame slot carries its own ownership bookkeeping — a paired
        # `__saw_forget` when the frame hands its reference over, codegen's
        # frame-read retain when it does not. The pre-transform AST was already
        # judged at this checkpoint as the plain local it was, and the whole
        # program is re-checked afterwards, so weighing in on the projection
        # would judge one read twice. `_check_payload_read` has carried this
        # guard since design 131; the un-projected path needs it for the same
        # reason, and needed it the moment `Result<T, E>` gained a tier.
        if getattr(expr, 'frame_place_read', False):
            return

        # design 131: a type carrying a deinit but NO copy policy used to fall
        # through every arm below and take the default bitwise path — an alias
        # whose two halves each ran `deinit` (DF-128a). Declaring `Deinit` alone
        # is now rejected at the conformance, so this state is unreachable; the
        # arm stays as a tripwire, because reaching it silently is a double free.
        if (self._is_deinit_type(src_type)
                and not self._is_no_copy_type(src_type)
                and not self._is_explicit_copy_type(src_type)
                and not self._is_implicit_copy_type(src_type)):
            self._error(
                ErrorKind.CANNOT_COPY,
                f"internal error: `{src_type}` carries a deinit but no copy "
                f"policy, so this transfer has no defined ownership rule",
                line, column,
                hint="this is a compiler bug — a copy policy is required at the "
                     "conformance, so no such type should exist"
            )
            return

        # design 139: ONE policy lookup decides this transfer. The chain used to
        # end in a bespoke owning-enum arm — a retain that fired only for a
        # structurally-Copy enum, and left every OTHER wrapper (an
        # `Optional`, a tuple, a `Result`) with no tier at all, so a move-only
        # payload inside one fell past every arm to a silent bitwise alias that
        # double-dropped (DF-131a). The oracle folds that enum case into the
        # 'implicit' tier and answers for the wrappers at the same time.
        tier = self.namespace.copy_tier(src_type)
        if tier == 'nocopy':
            if self._is_aliasing_expr(expr):
                if is_return:
                    self._error(
                        ErrorKind.CANNOT_COPY,
                        f"cannot return NoCopy type `{src_type}` without `move` in {context}",
                        line, column,
                        hint=self._transfer_refusal_hint(src_type, expr, 'nocopy')
                    )
                else:
                    self._error(
                        ErrorKind.CANNOT_COPY,
                        f"cannot copy value of type `{src_type}` which implements NoCopy",
                        line, column,
                        hint=self._transfer_refusal_hint(src_type, expr, 'nocopy')
                    )
        elif tier == 'explicit':
            # ExplicitCopy gets the same move-required treatment as NoCopy:
            # the compiler never implicitly duplicates it. Duplication must be a
            # visible `.copy()`; a plain transfer must be a `move`.
            if self._is_aliasing_expr(expr):
                self._error(
                    ErrorKind.CANNOT_COPY,
                    f"cannot copy value of type `{src_type}` which implements ExplicitCopy",
                    line, column,
                    hint=self._transfer_refusal_hint(src_type, expr, 'explicit')
                )
        elif tier == 'implicit':
            if self._is_aliasing_expr(expr):
                expr.needs_copy = True
        elif tier == 'abstract':
            # design 219 wave C, entry point 1. `'abstract'` used to fall off
            # the end of this chain — the whole of DF-217i: a generic body was
            # judged once with `T` abstract, the most permissive answer, and
            # nothing re-judged it at instantiation. The transfer now RAISES A
            # REQUIREMENT on the type parameters it names, which every call
            # site discharges against its concrete argument.
            if self._is_aliasing_expr(expr):
                self._tier_req_transfer(expr, src_type, line, column,
                                        is_return=is_return)

    def _transfer_refusal_hint(self, src_type: SawType, expr: Expression,
                               tier: str) -> str:
        """The spellings a refused whole-value transfer can be rewritten to.

        An OPTIONAL gets its own list (design 139). It is a place with a payload,
        so it has a third way out that no plain struct has: `o.take()` writes
        `None` back and hands the payload over, which works on a FIELD, where
        `move` cannot go (no partial moves). Naming only `move` and `.copy()`
        would send an author with a `File?` field down a path that does not
        exist.
        """
        # design 219 unit A2(b): a value read out of a POINTER place. The place
        # tracks no occupancy, so this is a TRANSFER — nothing is duplicated and
        # nothing is left behind — and `move` is the spelling that declares it.
        # Naming `move <binding>` here would send the author at the pointer, and
        # naming `.copy()` alone would hide that the read already moves.
        if getattr(expr, 'pointer_place', False):
            place = self._render_lvalue_path(expr)
            if tier == 'explicit':
                return (f"this read transfers ownership — spell it "
                        f"`move {place}`, or `{place}.copy()` to duplicate the "
                        f"element and leave the slot occupied")
            return (f"this read transfers ownership — spell it "
                    f"`move {place}`")
        if src_type is not None and src_type.kind == TypeKind.OPTIONAL:
            path = self._render_place(expr) if self._is_aliasing_expr(expr) else "the optional"
            parts = []
            if tier == 'explicit':
                parts.append(f"`{path}.copy()` for an explicit deep copy")
            if isinstance(expr, Identifier):
                parts.append(f"`move {path}` to transfer the whole binding")
            parts.append(f"`{path}.take()` to move the payload out in place")
            return "use " + ", ".join(parts[:-1]) + (", or " if len(parts) > 1 else "") + parts[-1]
        if tier == 'explicit':
            return ("use .copy() for an explicit deep copy, or `move` to "
                    "transfer ownership")
        return "use `move` to transfer ownership instead"

    def _check_no_copy_return(self, return_type: SawType, final_expr: Optional[Expression],
                               context_name: str, line: int, column: int):
        """Validate an implicit tail return of a NoCopy type uses `move`.

        Thin wrapper delegating to the shared value-transfer checkpoint so that
        implicit tail returns and explicit `return x` statements enforce the
        same rule.
        """
        self._check_value_transfer(final_expr, return_type, context_name,
                                    line, column, is_return=True)

    # ------------------------------------------------------------------
    # Static exclusivity check for by-reference arguments (design 08/10).
    #
    # Law of exclusivity -- "many readers XOR one writer", per call: an access
    # path passed mutably (`&var x`, or the receiver of a `var self` method)
    # must be disjoint from every OTHER by-reference path in the same call.
    # Immutable `&` paths may overlap each other freely (unobservable with no
    # writer). A `move` argument may not alias any reference argument.
    #
    # References cannot escape in Saw (no reference fields/returns, closures
    # capture by value), so every live reference was created at some call
    # expression on the stack. Aliasing therefore reduces to per-call-site
    # path disjointness plus forwarding -- and forwarding is covered because a
    # callee's `var` params are distinct storage unless the caller aliased
    # them, which the caller's own call-site check rejects. Hence fully static.
    # ------------------------------------------------------------------

    # Sentinel for an array index that is not a compile-time constant.
    _DYNAMIC_INDEX = object()

    @staticmethod
    def _place_use_receiver(node):
        """The receiver a `borrows` place use borrows, or None (design 188 u2).

        A place use is a node the checker resolved to a `borrows` accessor —
        `v[i]`, `m[k]`, `p.at(0)`, `v.get(i)` — and it is NOT an ordinary
        projection: the accessor call borrows the WHOLE receiver for the
        window's extent, which is what "a place borrow charges its ROOT" has
        said since design 146. (`place_uses.is_place` is the same test; it is
        spelled out here so the checker keeps no dependency on the lowering.)
        """
        if getattr(node, 'place_struct', None) is None:
            return None
        if getattr(node, 'place_lowered', False):
            return None
        if isinstance(node, ArrayIndex):
            return node.array_expr
        return getattr(node, 'object', None)

    def _build_access_path(self, expr: Expression):
        """Build an access path (root, projections) from an lvalue expression.

        root is a local/param name or 'self'. Each projection is one of
        ('field', name), ('tuple', int), or ('index', const_int | _DYNAMIC_INDEX).
        Returns None for a non-path expression (call result, literal, etc.) --
        those cannot legally appear under `&`/`&var` (rejected earlier by the
        lvalue check in `_check_reference_expr`).

        A PLACE USE is the one node that does not project (design 188 unit 2):
        it charges its receiver whole. Two windows onto one root, or a window
        beside a `&var root`, are therefore two overlapping accesses in one
        call — which is exactly what they are at runtime, and what silently lost
        writes until the roots joined this check (DF-188f).
        """
        projections = []
        node = expr
        while True:
            place_receiver = self._place_use_receiver(node)
            if place_receiver is not None:
                # Whatever was projected out of the place sits INSIDE the
                # window, and the window holds the whole receiver — so the
                # projections below it say nothing about disjointness and the
                # index arguments are not a path component at all.
                projections = []
                node = place_receiver
                continue
            if isinstance(node, Identifier):
                projections.reverse()
                return (node.name, tuple(projections))
            if isinstance(node, SelfExpr):
                projections.reverse()
                return ('self', tuple(projections))
            if isinstance(node, MemberAccess):
                projections.append(('field', node.member))
                node = node.object
            elif isinstance(node, (BindOptional, OptionalEvalExpr)):
                # An `?.` hop / chain wrapper (design 111) is transparent for
                # access-path purposes: the root and its field/index projections
                # are what determine overlap; the optional unwrap adds no path
                # component.
                node = node.expr
            elif isinstance(node, TupleIndex):
                projections.append(('tuple', node.index))
                node = node.tuple_expr
            elif isinstance(node, ArrayIndex):
                if isinstance(node.index, IntLiteral):
                    projections.append(('index', node.index.value))
                else:
                    projections.append(('index', self._DYNAMIC_INDEX))
                node = node.array_expr
            else:
                return None

    def _paths_overlap(self, a, b) -> bool:
        """Two access paths overlap iff they may denote overlapping storage.

        Different roots -> disjoint. Same root: walk projections in parallel;
        differing fields / tuple indices / differing *constant* array indices at
        the same position -> disjoint; a DYNAMIC index at a position overlaps
        anything there (conservative). Running out of projections on either side
        (one is a prefix of the other) -> overlap.

        Only ever consulted for pairs where at least one side is mutable/moved,
        so the dynamic-index conservatism applies exactly where the decision
        requires it.
        """
        root_a, proj_a = a
        root_b, proj_b = b
        if root_a != root_b:
            return False
        for pa, pb in zip(proj_a, proj_b):
            if pa[0] != pb[0]:
                # Different projection kinds on the same root cannot denote the
                # same storage.
                return False
            if pa[0] == 'index':
                ia, ib = pa[1], pb[1]
                if ia is self._DYNAMIC_INDEX or ib is self._DYNAMIC_INDEX:
                    continue
                if ia != ib:
                    return False
            else:
                if pa[1] != pb[1]:
                    return False
        return True

    def _render_lvalue_path(self, expr: Expression) -> str:
        """Render an lvalue expression as a source-like path (for diagnostics)."""
        if isinstance(expr, Identifier):
            return expr.name
        if isinstance(expr, SelfExpr):
            return 'self'
        if isinstance(expr, MemberAccess):
            return f"{self._render_lvalue_path(expr.object)}.{expr.member}"
        if isinstance(expr, TupleIndex):
            return f"{self._render_lvalue_path(expr.tuple_expr)}.{expr.index}"
        if isinstance(expr, ArrayIndex):
            return f"{self._render_lvalue_path(expr.array_expr)}[{self._render_index(expr.index)}]"
        if isinstance(expr, MethodCall):
            # A named place accessor (`p.at(0)`, `m.get(k)`) — a by-reference
            # access since design 188 unit 2, so it has to render.
            return (f"{self._render_lvalue_path(expr.object)}."
                    f"{expr.method_name}(…)")
        return "<expr>"

    def _render_index(self, expr: Expression) -> str:
        if isinstance(expr, IntLiteral):
            return str(expr.value)
        if isinstance(expr, Identifier):
            return expr.name
        return "…"

    def _check_reference_sigils(self, values, param_types, param_names=None):
        """Validate each reference argument's sigil against its parameter (design 34).

        Call sites mirror the parameter's reference spelling: `&x` lends to a
        `&T` parameter, `&var x` lends to a `&var T` parameter. A mismatch in
        EITHER direction is a compile error. `values` are the argument value
        expressions; `param_types` is positionally aligned; `param_names`
        (optional) names the parameter in the diagnostic when available.
        """
        if not param_types:
            return
        for i, value in enumerate(values):
            if not isinstance(value, ReferenceExpr):
                continue
            if i >= len(param_types):
                continue
            ptype = param_types[i]
            if ptype is None or ptype.kind != TypeKind.REFERENCE:
                # Bare `&`/`&var` against a by-value parameter is a plain type
                # mismatch, already reported by the caller's compatibility check.
                continue
            name = param_names[i] if param_names and i < len(param_names) else None
            named = f"parameter `{name}` is " if name else "parameter is "
            rendered = self._render_lvalue_path(value.expr)
            if ptype.reference_mutable and not value.mutable:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"{named}`&var {ptype.inner_type}`; write `&var {rendered}`",
                    value.line, value.column,
                    hint="call sites mirror the parameter's reference spelling"
                )
            elif not ptype.reference_mutable and value.mutable:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"{named}`&{ptype.inner_type}`; write `&{rendered}`",
                    value.line, value.column,
                    hint="call sites mirror the parameter's reference spelling"
                )

    @staticmethod
    def _nested_reference_exprs(expr):
        """Every `&`/`&var` written strictly BELOW `expr`, in SOURCE order
        (design 188 unit 2; unconditional since design 199).

        The outermost reference of `expr` itself is not one of them — a
        top-level `&var x` argument is collected by the caller — and a
        reference found below one is not descended into further, because the
        outer path already covers it.

        Two things the walk deliberately does not enter: a CLOSURE (whose
        borrow captures are collected from `capture_specs` instead, and whose
        body runs where the callee decides) and a type (`SawType` is not an
        AST node, so `child_nodes` never yields one).

        Riding `ast_walk.child_nodes` is what makes the coverage the same
        coverage every other walk has — design 193 unit 3's point being that a
        hand-rolled recursion drifts over the shape nobody's own caller
        reached, and this one is asked about `Wrap(inner: &var p)` and
        `{"k": &var p}`, both of which are tuple-shaped fields.
        """
        found = []
        seen = set()

        def walk(node, is_root):
            if id(node) in seen or isinstance(node, ClosureExpr):
                return
            seen.add(id(node))
            if isinstance(node, ReferenceExpr) and not is_root:
                found.append(node)
                return
            for child in child_nodes(node):
                walk(child, False)

        walk(expr, True)
        return found

    # ------------------------------------------------------------------
    # design 189: scoped task borrows — the capture's extent is the task's life.
    #
    # Every rule below is the Law of Exclusivity already in this file, read over
    # a longer window. A `[&var x]` capture into `group.spawn(...)` opens an
    # EXCLUSIVE borrow of `x`'s root and a `[&x]` capture a SHARED one; the
    # borrow lives until the task's HANDLE is joined, or — for a handle that is
    # discarded, stored, or simply never joined — until the group's `Deinit`
    # joins its children at scope exit. Nothing here is a new checker: the
    # access sites feed the same overlap question the per-call check asks, from
    # a set that outlives the statement that opened it.
    #
    # Probed Aug 9 (design 189's record): without the extent, `move buf` between
    # a spawn and its join hands the task freed memory, silently, exit 0.
    # ------------------------------------------------------------------

    _TASK_HANDLE_TYPES = ("TaskHandle", "VoidTaskHandle")

    def _task_borrow_for(self, var_info, writes: bool):
        """The first live task borrow an access to `var_info` collides with.

        An EXCLUSIVE `[&var x]` capture excludes every other touch of the root,
        reads included — the standard one-writer-XOR-many-readers table over a
        task-length window (ratified Aug 9). A caller that wants to observe
        mid-task state reaches for `Arc<Mutex<T>>` or a `Channel`, where the
        synchronization is visible in the types. A SHARED `[&x]` capture
        composes with other readers and collides only with a write or a move.
        """
        if not self._task_borrows or var_info is None:
            return None
        for b in self._task_borrows:
            if b.root_id == var_info.binding_id and (b.mutable or writes):
                return b
        return None

    def _task_borrow_for_name(self, root_name, writes: bool):
        """`_task_borrow_for` starting from an access path's root name."""
        if not self._task_borrows or root_name is None:
            return None
        return self._task_borrow_for(self.current_scope.lookup(root_name), writes)

    def _task_borrow_extent(self, b) -> str:
        """The sentence naming the task and where its borrow is released."""
        sigil = "&var" if b.mutable else "&"
        if b.handle_name is not None:
            release = f"`{b.handle_name}.join()` releases it"
        elif b.group_name is not None:
            release = (f"its group `{b.group_name}` is torn down at the end of "
                       f"this scope (nothing joins its handle)")
        else:
            release = "its group is torn down at the end of this scope"
        return (f"the task spawned at line {b.spawn_line} holds "
                f"`{sigil} {b.root_name}` until {release}")

    def _report_task_borrow(self, b, what: str, line: int, column: int,
                            root: Optional[str] = None):
        """Report an access that collides with a live task-capture borrow.

        `what` is the existing exclusivity/move vocabulary for the access —
        design 189 adds one sentence (the extent), not a new error family.
        """
        if line in b.reported:
            # One statement reaches a root several times on the way down (the
            # receiver of `buf.push(9)` is checked as an expression and again as
            # an access-set entry); one diagnostic is the useful number.
            return
        b.reported.add(line)
        name = root or b.root_name
        if what == 'move':
            message = (f"cannot `move` `{name}` while a spawned task borrows "
                       f"it: {self._task_borrow_extent(b)}")
        else:
            phrase = {
                'read': f"`{name}` cannot be read here",
                'write': f"`{name}` cannot be written here",
                'capture': f"`{name}` cannot be captured into another task here",
                'access': f"`{name}` cannot be accessed by reference here",
            }[what]
            message = (f"exclusive access violation: {phrase} — "
                       f"{self._task_borrow_extent(b)}")
        join_hint = (f"`{b.handle_name}.join()`" if b.handle_name
                     else "joining the task's handle")
        self._error(
            ErrorKind.EXCLUSIVITY_VIOLATION, message, line, column,
            hint=f"join the task first — {join_hint} ends the borrow, and the "
                 f"spawn-join-use order stays legal. To watch the value WHILE "
                 f"the task runs, share it through an `Arc<Mutex<T>>` or a "
                 f"`Channel`, where the synchronization is visible in the types"
        )

    def _release_task_borrows_for_handle(self, handle_name: str) -> None:
        """`h.join()` — a consuming, statically known release point."""
        if not self._task_borrows:
            return
        info = self.current_scope.lookup(handle_name)
        if info is None or info.type is None:
            return
        if (info.type.kind != TypeKind.STRUCT
                or info.type.struct_name not in self._TASK_HANDLE_TYPES):
            return
        self._task_borrows = [b for b in self._task_borrows
                              if b.handle_id != info.binding_id]

    def _bind_task_borrow_handle(self, var_info, name: str) -> None:
        """Hand the borrows a spawn just opened to the binding that took its
        handle. A handle that is never bound (`group.spawn(f())` as a statement,
        `let _ = ...`) keeps `handle_id = None` and releases at group death."""
        pending = self._pending_task_borrows
        if not pending or var_info is None or var_info.type is None:
            return
        if (var_info.type.kind != TypeKind.STRUCT
                or var_info.type.struct_name not in self._TASK_HANDLE_TYPES):
            return
        for b in pending:
            b.handle_id = var_info.binding_id
            b.handle_name = name
        self._pending_task_borrows = []

    def _close_task_borrow_scope(self, scope, entry_borrows) -> None:
        """End-of-block bookkeeping for task-capture borrows (design 189).

        A group dies at the end of the scope that declared it and its `Deinit`
        joins its children there, so every borrow it still carries is released;
        a borrow whose ROOT dies here goes with it (design 188 unit 5 already
        refuses the ordering where that root is the one being borrowed).

        A borrow that was live on the way IN but was joined inside this block
        comes back. The join was on one path only — the other path never joined
        — so the conservative answer is that it is still held.
        """
        if not self._task_borrows and not entry_borrows:
            return
        dead = {v.binding_id for v in scope.variables.values()}
        kept = [b for b in self._task_borrows
                if b.group_id not in dead and b.root_id not in dead]
        live = {id(b) for b in kept}
        kept.extend(b for b in entry_borrows
                    if id(b) not in live
                    and b.group_id not in dead and b.root_id not in dead)
        for b in kept:
            if b.handle_id in dead:
                # The HANDLE died unjoined. Its `Deinit` owns nothing and does
                # not join (design 134 — the result stays in the group's cell),
                # so the borrow survives; only its release point moves, to the
                # group's death. Say so rather than naming a binding that is no
                # longer in scope.
                b.handle_id, b.handle_name = None, None
        self._task_borrows = kept

    def _check_call_exclusivity(self, values, param_types=None,
                                receiver: Optional[Expression] = None,
                                receiver_mutable: bool = False,
                                param_names=None):
        """Enforce the law of exclusivity across one call's by-reference paths.

        `values` are the argument value expressions; `param_types` (optional,
        positionally aligned). `receiver`/`receiver_mutable` describe a method
        receiver: the receiver of a `var self` method is a mutable path.

        Reference-argument sigils are validated first (design 34): after that,
        each `&`/`&var` argument's mutability is read straight from its sigil,
        which agrees with the parameter by construction.

        By-value arguments are NOT collected -- snapshot semantics (the copy
        happens at call setup), which is what makes a by-value argument that
        overlaps a `&var` well-defined.

        THE ACCESS SET, in collection order: the receiver; each `&`/`&var`
        argument; each `move` argument; each `o.take()` argument's receiver
        (design 131 -- it writes `None` back during call setup); each borrow
        CAPTURE of a closure argument (design 16/29); and each `&`/`&var` a
        NESTED call in this argument list creates (design 199 -- an argument's
        borrow extends over the whole call expression). Live task-capture
        borrows are cross-checked against the whole set (design 189) before the
        pairwise overlap pass runs within it.

        ENTRY POINTS (obligation 1 -- a funnel names its entries). Every call
        form in the language reaches the Law through here, and all fifteen live
        in `typechecker/expressions.py`:
          * `_check_function_call` (two sites: the plain call and the generic
            instantiation), `_check_overloaded_function_call`
          * `_check_method_call`, `_check_overloaded_method_call`,
            `_check_field_call` (a call through a closure-typed field),
            `_check_type_param_method_call`, `_check_existential_method_call`
          * `_check_static_method_call`, `_check_overloaded_static_method_call`
          * `_check_module_function_call`, `_check_overloaded_module_function_call`
          * `_init_matches` and `_check_module_struct_init` -- a memberwise
            struct literal, whose field values are argument positions
          * `_check_optional_take` -- `o.take()` as a call in its own right
            (receiver only, no arguments)
        A new call form that does not route through this method is a hole in
        the Law, not a missing feature: add the entry here and to this list.
        """
        # Validate that each reference argument's sigil matches its parameter.
        self._check_reference_sigils(values, param_types, param_names)
        # Each entry: (kind, path, name_expr, line, column) where kind is one of
        # 'mut', 'imm', 'moved'. name_expr renders the offending path.
        entries = []
        # The entries that came from a closure's CAPTURE list, so design 189's
        # cross-check can say "captured into another task" rather than the
        # generic by-reference phrasing.
        capture_entries = set()

        # A method receiver is always a borrow (`&self`/`&var self` -- the parser
        # requires it; static/init calls pass receiver=None). Collect it either
        # way: a `var self` receiver is a mutable path, and an immutable `&self`
        # receiver is a live shared read for the call's duration, so aliasing it
        # with a `&var` argument (`c.read(&var c)`) is an exclusivity violation.
        if receiver is not None:
            path = self._build_access_path(receiver)
            if path is not None:
                entries.append(('mut' if receiver_mutable else 'imm', path,
                                receiver, receiver.line, receiver.column))

        if param_types is None:
            param_types = []
        for i, value in enumerate(values):
            if isinstance(value, ReferenceExpr):
                path = self._build_access_path(value.expr)
                if path is None:
                    continue
                # Mutability comes from the sigil; `_check_reference_sigils` has
                # already ensured it agrees with the parameter (design 34).
                is_mut = bool(value.mutable)
                entries.append(('mut' if is_mut else 'imm', path, value.expr,
                                value.line, value.column))
            elif isinstance(value, MoveExpr):
                entries.append(('moved', (value.variable, ()), value,
                                value.line, value.column))
            elif getattr(value, 'optional_take', False):
                # design 131: a by-value argument is normally snapshot semantics
                # and stays out of the access set — but `o.take()` WRITES `None`
                # back into its receiver while the call is being set up, so its
                # receiver path is a mutable access of this call, exactly like a
                # `&var` argument. `f(&var h, h.s.take())` is a real conflict.
                path = self._build_access_path(value.object)
                if path is not None:
                    entries.append(('mut', path, value.object,
                                    value.line, value.column))
            elif isinstance(value, ClosureExpr):
                # design 16/29 item 4: the borrow captures of a non-escaping
                # closure argument are hidden reference parameters of THIS call,
                # so they join the access set — checked pairwise against the
                # receiver, the other arguments, and the other closures' captures.
                # `v.each { [&var v] in ... }` (mutably capturing the iterated
                # collection) collides with the `&self` receiver and is rejected;
                # a disjoint `[&total]` is fine.
                for spec in (getattr(value, 'capture_specs', None) or []):
                    if spec.mode not in ('ref', 'ref_var'):
                        continue
                    name_expr = Identifier(name=spec.name, line=spec.line,
                                           column=spec.column)
                    path = self._build_access_path(name_expr)
                    if path is None:
                        continue
                    capture_entries.add(id(name_expr))
                    entries.append(('mut' if spec.mode == 'ref_var' else 'imm',
                                    path, name_expr, spec.line, spec.column))

        # An argument's borrow extends over the WHOLE call expression, nested
        # calls included (design 199, closing DF-188j): a `&`/`&var` written
        # inside a nested call in this argument list JOINS this call's access
        # set and meets the same overlap test as everything else in it.
        # `sink(&var p.a, reset(&var p))` is two by-reference accesses of one
        # root live over one call, and which of them the program observes is
        # argument evaluation order.
        #
        # Design 188 unit 2 landed the half where a PLACE window is open,
        # because a window's extent is provably the whole call; the ruling
        # generalizes it — the same shape spelled through an accessor was
        # already refused, and the inconsistency had no principle behind it.
        # DISJOINT paths stay legal, so `f(&var x, g(&y))` compiles; the
        # widening is to the access SET, never to the overlap test.
        nested_entries = set()
        for value in values:
            for ref in self._nested_reference_exprs(value):
                path = self._build_access_path(ref.expr)
                if path is None:
                    continue
                nested_entries.add(id(ref.expr))
                entries.append(('mut' if ref.mutable else 'imm', path,
                                ref.expr, ref.line, ref.column))

        # design 189: a live task-capture borrow is an access that OUTLIVES this
        # statement, so every by-reference access this call makes is checked
        # against it before the pairwise pass looks within the call. This is the
        # one hook the spawn-capture case needs: a second `[&var n]` capture is
        # an ordinary capture entry, and it collides with the first task's
        # borrow exactly the way two captures in one call collide.
        if self._task_borrows:
            for kind, path, e, ln, col in entries:
                b = self._task_borrow_for_name(path[0], kind != 'imm')
                if b is not None:
                    self._report_task_borrow(
                        b, 'capture' if id(e) in capture_entries else 'access',
                        ln, col, root=path[0])

        n = len(entries)
        for i in range(n):
            ki, pi, ei, li, ci = entries[i]
            for j in range(i + 1, n):
                kj, pj, ej, lj, cj = entries[j]
                if ki == 'imm' and kj == 'imm':
                    continue
                if not self._paths_overlap(pi, pj):
                    continue
                moved_side = None
                if ki == 'moved' and kj != 'moved':
                    moved_side = (ei, li, ci)
                elif kj == 'moved' and ki != 'moved':
                    moved_side = (ej, lj, cj)
                if moved_side is not None:
                    m_expr, m_line, m_col = moved_side
                    self._error(
                        ErrorKind.EXCLUSIVITY_VIOLATION,
                        f"cannot `move` `{self._render_move(m_expr)}` while it is "
                        f"also passed by reference in the same call",
                        m_line, m_col,
                        hint="a moved value cannot alias a reference argument in the same call"
                    )
                    continue
                if ki == 'moved' and kj == 'moved':
                    # Two moves of overlapping storage -- outside this brief's
                    # scope (no reference involved); leave to move analysis.
                    continue
                # At least one side is mutable and it overlaps another path.
                if ki == 'mut':
                    m_expr, m_line, m_col = ei, li, ci
                    other = ej
                else:
                    m_expr, m_line, m_col = ej, lj, cj
                    other = ei
                # A place window is not an ordinary path, so it gets the
                # diagnostic that says what it holds (design 188 unit 2).
                place = next((e for e in (m_expr, other)
                              if self._place_use_receiver(e) is not None), None)
                if place is not None:
                    root = self._render_lvalue_path(
                        self._place_use_receiver(place))
                    self._error(
                        ErrorKind.EXCLUSIVITY_VIOLATION,
                        f"exclusive access violation: the place "
                        f"`{self._render_lvalue_path(place)}` borrows `{root}` "
                        f"for the whole window, and `{root}` is accessed by "
                        f"reference a second time in the same call",
                        m_line, m_col,
                        hint="a place borrow charges its ROOT, so two windows "
                             "onto one receiver — or a window beside a `&var` "
                             "of it — cannot both be open. Open them in "
                             "SEPARATE statements, or reach for the method that "
                             "does both at once (`v.swap(i, j)`)"
                    )
                    continue
                # A reference a NESTED call created gets the diagnostic that
                # says where it came from (design 199), because nothing at this
                # call's top level names it: the fix is to hoist the nested
                # call into its own `let`, not to change a sigil.
                nested = next((e for e in (ej, ei) if id(e) in nested_entries),
                              None)
                if nested is not None:
                    other = ei if nested is ej else ej
                    root = pi[0]
                    n_line = lj if nested is ej else li
                    n_col = cj if nested is ej else ci
                    self._error(
                        ErrorKind.EXCLUSIVITY_VIOLATION,
                        f"exclusive access violation: "
                        f"`{self._render_lvalue_path(nested)}` is borrowed by a "
                        f"nested call in this argument list while "
                        f"`{self._render_lvalue_path(other)}` is also accessed "
                        f"by reference in the same call — both reach `{root}`",
                        n_line, n_col,
                        hint="an argument's borrow extends over the whole call "
                             "expression, nested calls included, so the two "
                             "overlap and which one the program observes is "
                             "argument evaluation order. Hoist the nested call "
                             "into its own `let` so the borrows are in separate "
                             "statements; disjoint paths need no change "
                             "(`f(&var x, g(&y))` is fine)"
                    )
                    continue
                self._error(
                    ErrorKind.EXCLUSIVITY_VIOLATION,
                    f"exclusive access violation: `{self._render_lvalue_path(m_expr)}` "
                    f"is passed as `&var` while also being accessed in the same call",
                    m_line, m_col,
                    hint="disjoint access paths are allowed (e.g. `&var p.x` with `&p.y`); "
                         "give the mutable reference exclusive access"
                )

    def _render_move(self, expr: Expression) -> str:
        if isinstance(expr, MoveExpr):
            return expr.variable
        return self._render_lvalue_path(expr)

    def _check_integer_literal_range(self, literal: IntLiteral, target_type: SawType):
        """Check if an integer literal fits in the target fixed-width integer type."""
        # Define ranges for each integer type
        # INT and UINT are system-width (64-bit on most platforms)
        ranges = {
            TypeKind.INT: (-9223372036854775808, 9223372036854775807),
            TypeKind.UINT: (0, 18446744073709551615),
            TypeKind.INT8: (-128, 127),
            TypeKind.INT16: (-32768, 32767),
            TypeKind.INT32: (-2147483648, 2147483647),
            TypeKind.INT64: (-9223372036854775808, 9223372036854775807),
            TypeKind.UINT8: (0, 255),
            TypeKind.UINT16: (0, 65535),
            TypeKind.UINT32: (0, 4294967295),
            TypeKind.UINT64: (0, 18446744073709551615),
        }

        if target_type.kind not in ranges:
            return  # Not a fixed-width type, no range check needed

        min_val, max_val = ranges[target_type.kind]
        if literal.value < min_val or literal.value > max_val:
            type_name = target_type.kind.name
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"integer literal {literal.value} out of range for {type_name} ({min_val} to {max_val})",
                literal.line, literal.column
            )

    def _member_copy_type(self, field_type: SawType) -> SawType:
        """The type a FIELD contributes to its container's copy policy.

        The identity everywhere but on an interior-mutability cell (design 186),
        which contributes its `T`. A cell is `NoCopy` as a value — copying one
        makes a second cell — but it does not force `NoCopy` onto whatever holds
        it: the container states its own policy, which is what keeps
        `Atomic<Int>` bitwise-copyable and makes the wrapper idiom's
        `extension Cell<T>: NoCopy {}` a line the reader can see rather than a
        cascade they cannot.
        """
        return self.namespace.cell_payload(field_type) or field_type

    def _check_no_copy_containment(self):
        """Check that structs containing NoCopy fields also implement NoCopy."""
        for struct_name, struct_info in self.namespace.structs.items():
            # design 62 G1: compiler-synthesized coroutine frames are never copied
            # (constructed, resumed by `&var`, dropped in place), so a NoCopy field
            # such as a frame-resident `TaskGroup` is sound without a NoCopy
            # conformance. (Their owning fields are torn down memberwise.)
            if struct_name.startswith("__Frame_"):
                continue
            # Skip if struct already implements NoCopy
            if self.namespace.type_conforms_to(struct_name, "NoCopy"):
                continue

            # Check each field
            for field_name, field_type in struct_info.fields.items():
                # A closure FIELD never forces the struct NoCopy (design 73):
                # closures are Copy, so a closure-bearing struct copies by
                # retaining the closure's env (handled like a String field below).
                if field_type is not None and field_type.kind == TypeKind.FUNCTION:
                    continue
                if self._is_no_copy_type(self._member_copy_type(field_type)):
                    self._error(
                        ErrorKind.CANNOT_COPY,
                        f"struct `{struct_name}` contains NoCopy field `{field_name}` of type `{field_type}` but does not implement NoCopy",
                        struct_info.line, struct_info.column,
                        hint=f"add `extension {struct_name}: NoCopy {{}}` — a "
                             f"NoCopy field makes `{struct_name}` move-only, and "
                             f"its `deinit` is synthesized"
                    )
                    break  # Only report once per struct

    # ------------------------------------------------------- design 188 (unit 4)

    def _no_move_members(self, type_name: str):
        """`(member name, member type)` pairs of `type_name` that are NoMove."""
        struct_info = self.namespace.structs.get(type_name)
        if struct_info is not None:
            return [(n, t) for n, t in struct_info.fields.items()
                    if self._is_no_move_type(t)]
        enum_info = self.namespace.enums.get(type_name)
        if enum_info is not None:
            out = []
            for payloads in enum_info.variants.values():
                for pname, ptype in (payloads or []):
                    if self._is_no_move_type(ptype):
                        out.append((pname, ptype))
            return out
        return []

    def _check_no_move_declarations(self):
        """`NoMove` REQUIRES a declared `NoCopy`, and CONTAINMENT cascades.

        Duplication and relocation are separate axes (design 188 unit 4), so
        neither property is ever inferred from the other. Declaring `NoMove` on
        a type whose copy tier is anything but a DECLARED `NoCopy` is an error:
        both facts are stated out loud, which is also what keeps `NoMove +
        ExplicitCopy` — the C++ re-register-on-copy shape — available later by
        relaxing exactly this check and nothing else.

        The containment rule is design 139's declared cascade, not silent
        inheritance: a struct or enum with a NoMove member does not compile
        until it says `NoMove` (and `NoCopy`) itself. The cost is real and the
        spec states it; the escape for a type that wants a movable handle over
        pinned state is composition — put the pinned part behind a heap
        indirection, which needs no language mechanism.
        """
        for type_name in list(self.namespace.structs) + list(self.namespace.enums):
            # A compiler-synthesized coroutine frame is constructed, resumed by
            # `&var` and dropped in place — it is never relocated, so a
            # frame-resident group needs no declaration (design 62 G1, the same
            # exemption the NoCopy containment check makes).
            if type_name.startswith("__Frame_"):
                continue
            declared = self.namespace.type_conforms_to(type_name, "NoMove")
            info = (self.namespace.structs.get(type_name)
                    or self.namespace.enums.get(type_name))
            line = getattr(info, 'line', 0) or 0
            column = getattr(info, 'column', 0) or 1

            if declared and self.namespace.declared_copy_tier(type_name) != 'nocopy':
                self._error(
                    ErrorKind.CANNOT_COPY,
                    f"`{type_name}` declares `NoMove` without declaring "
                    f"`NoCopy`: relocation and duplication are separate "
                    f"properties, and `NoMove` requires the other to be stated "
                    f"rather than implying it",
                    line, column,
                    hint=f"add `extension {type_name}: NoCopy {{}}` beside the "
                         f"`NoMove` conformance — a value that may not move and "
                         f"may be freely duplicated is not a shape v1 supports"
                )
                continue

            if declared:
                continue
            offenders = self._no_move_members(type_name)
            if not offenders:
                continue
            member, member_type = offenders[0]
            self._error(
                ErrorKind.CANNOT_COPY,
                f"`{type_name}` contains NoMove member `{member}` of type "
                f"`{member_type}` but does not declare `NoMove`: a value that "
                f"cannot be relocated cannot be relocated inside something else "
                f"either",
                line, column,
                hint=f"declare the cascade — `extension {type_name}: NoCopy {{}}` "
                     f"and `extension {type_name}: NoMove {{}}` — or hold the "
                     f"pinned value behind a heap indirection (a `Box`), which "
                     f"gives `{type_name}` a movable handle over storage that "
                     f"stays put"
            )

    def _check_implicit_copy_containment(self):
        """Check that structs containing Copy fields also implement a copy policy."""
        for struct_name, struct_info in self.namespace.structs.items():
            # Skip if struct already declares a copy policy or NoCopy.
            # (NoCopy types can contain Copy fields since they can't be
            # copied anyway; an ExplicitCopy struct copies the field explicitly
            # in its own copy().)
            if (self.namespace.declares_copy_tier(struct_name) or
                self.namespace.type_conforms_to(struct_name, "ExplicitCopy") or
                self.namespace.type_conforms_to(struct_name, "NoCopy")):
                continue

            # Check each field
            for field_name, field_type in struct_info.fields.items():
                # String is a compiler-known Copy value type; unlike a
                # user Rc it does not force containing structs to opt in (a plain
                # struct holding a String keeps the pre-refcount behavior:
                # bitwise field, no imposed copy/deinit policy). A fixed array of
                # String is exempt on the same footing (design 33): its per-element
                # retain/release is compiler-handled, so a `[String; N]` field does
                # not force a policy any more than a scalar `String` field does.
                if self._array_base_kind(field_type) == TypeKind.STRING:
                    continue
                # A closure field is a compiler-known Copy value (design
                # 73), exactly like String: its refcounted-env retain/release is
                # compiler-handled, so it does not force the struct to opt into a
                # copy policy. (A struct copy retains the closure env; struct drop
                # releases it — exactly once at the last owner.)
                if field_type is not None and field_type.kind == TypeKind.FUNCTION:
                    continue
                if self._is_implicit_copy_type(self._member_copy_type(field_type)):
                    self._error(
                        ErrorKind.CANNOT_COPY,
                        f"struct `{struct_name}` contains Copy field `{field_name}` of type `{field_type}` but does not implement Copy",
                        struct_info.line, struct_info.column,
                        hint=f"add `@synthesize extension {struct_name}: "
                             f"Copy {{}}` for a memberwise copy, or write "
                             f"`func copy(&self) -> {struct_name}` by hand"
                    )
                    break  # Only report once per struct

    def _check_explicit_copy_containment(self):
        """A struct holding a field the compiler cannot duplicate SILENTLY must
        declare its own copy policy (design 219's restatement).

        The rule used to read "contains an ExplicitCopy field"; with the tier
        collapse it reads "contains a field that is not on the merged `Copy`
        tier" — same set of offenders, stated as the one question the tier
        system now asks. A `NoCopy` field is caught by
        `_check_no_copy_containment`, which runs the move-only half of the same
        sentence; this one covers the fields that CAN be duplicated but only
        with ceremony, and so cannot ride a silent memberwise copy.
        """
        for struct_name, struct_info in self.namespace.structs.items():
            # design 62 G1: a compiler-synthesized coroutine frame is never
            # copied (constructed, resumed through `&var`, dropped in place), so
            # an ExplicitCopy field needs no conformance — the same exemption
            # `_check_no_copy_containment` already makes. It went unnoticed until
            # design 139 gave `Optional<T>` a tier: a frame stores each
            # across-suspend local as an optional field, so a spawned body over a
            # `Vector<Int>` parameter suddenly held an ExplicitCopy `v` field.
            if struct_name.startswith("__Frame_"):
                continue
            # Skip if struct already declares ExplicitCopy or NoCopy.
            # (NoCopy types can contain ExplicitCopy fields since they can't be
            # copied anyway.) Copy is NOT sufficient: an ExplicitCopy
            # field cannot be cheaply/implicitly duplicated.
            if (self.namespace.type_conforms_to(struct_name, "ExplicitCopy") or
                self.namespace.type_conforms_to(struct_name, "NoCopy")):
                continue

            # Check each field
            for field_name, field_type in struct_info.fields.items():
                if self._is_explicit_copy_type(self._member_copy_type(field_type)):
                    self._error(
                        ErrorKind.CANNOT_COPY,
                        f"struct `{struct_name}` contains ExplicitCopy field `{field_name}` of type `{field_type}` but does not implement ExplicitCopy",
                        struct_info.line, struct_info.column,
                        hint=f"pick a copy policy: `@synthesize extension "
                             f"{struct_name}: ExplicitCopy {{}}` for a memberwise "
                             f"deep copy, `func copy(&self) -> {struct_name}` by "
                             f"hand, or `extension {struct_name}: NoCopy {{}}` to "
                             f"make it move-only"
                    )
                    break  # Only report once per struct

    def _check_enum_policy_declared(self):
        """An enum with an owning payload must DECLARE its copy policy (design 139).

        The struct parity rule. A struct holding a `Vector` or a `File` has had
        to name its transfer class since design 9, because the compiler knows how
        to DESTROY such a value but not whether the author wants it duplicated.
        An enum with the same payload was answering that question by itself —
        silently, and only for the Copy case; a `Vector` or `File`
        payload got no tier at all and every transfer bitwise-aliased it.

        So the same question is now asked of enums, in the same words. Only the
        two OWNING tiers are demanded: an enum whose payloads are trivial or
        Copy keeps working undeclared, exactly as a String-field struct
        does, because the compiler handles those transfers on its own.

        A GENERIC enum is judged on its declaration, where a payload of type `T`
        is opaque and contributes no tier — so `Result` and any user
        `enum Wrap<T>` are never asked to declare something that depends on how
        they are instantiated. Each instantiation gets its tier from the
        structural join instead.
        """
        for enum_name, enum_info in self.namespace.enums.items():
            if self.namespace.declared_copy_tier(enum_name) != 'free':
                continue
            for variant_name, payloads in enum_info.variants.items():
                offender = next(
                    ((fname, ftype) for fname, ftype in payloads
                     if self.namespace.copy_tier(ftype) in ('explicit', 'nocopy')),
                    None)
                if offender is None:
                    continue
                field_name, field_type = offender
                tier = self.namespace.copy_tier(field_type)
                trait = 'NoCopy' if tier == 'nocopy' else 'ExplicitCopy'
                if tier == 'nocopy':
                    hint = (f"add `extension {enum_name}: NoCopy {{}}` — a NoCopy "
                            f"payload makes `{enum_name}` move-only, and its "
                            f"`deinit` is synthesized")
                else:
                    hint = (f"pick a copy policy: `@synthesize extension "
                            f"{enum_name}: ExplicitCopy {{}}` for a payload-deep "
                            f"copy, or `extension {enum_name}: NoCopy {{}}` to "
                            f"make it move-only")
                self._error(
                    ErrorKind.CANNOT_COPY,
                    f"enum `{enum_name}` carries {trait} payload `{field_name}` "
                    f"of type `{field_type}` in variant `{variant_name}` but "
                    f"does not implement {trait}",
                    getattr(enum_info, 'line', 0), getattr(enum_info, 'column', 0),
                    hint=hint
                )
                break  # Only report once per enum

    def _check_copy_trait_exclusivity(self):
        """DELETED by design 219 — the two are no longer alternatives.

        The check existed because the two names (`ImplicitCopy` as it was then
        spelled, and `ExplicitCopy`) named two TIERS, and a type on two tiers
        has no answer to "what does a transfer cost".
        After the collapse they name different things: `Copy` is the tier, and
        `ExplicitCopy` is an
        ordinary trait every Copy type satisfies anyway. Declaring both is
        therefore redundant rather than contradictory — a `copy()` on a Copy
        type is the same operation the compiler would have inserted — so there
        is nothing left to refuse.

        Kept as a named no-op rather than deleted at the call site: the pass
        list is the readable census of what registration checks, and a removed
        rule is worth reading in the place it used to run.
        """
        return

    def _check_derivable_copy(self):
        """A struct with a compiler-derived memberwise copy() cannot contain a
        NoCopy field: NoCopy values can never be duplicated, so the member cannot
        be copied. Runs after all conformances are registered so field copy tiers
        are known regardless of declaration order."""
        for struct_name in self._derived_copy_structs:
            struct_info = self.namespace.structs.get(struct_name)
            if struct_info is None:
                continue
            for field_name, field_type in struct_info.fields.items():
                if self._is_no_copy_type(field_type):
                    self._error(
                        ErrorKind.CANNOT_COPY,
                        f"cannot derive copy() for `{struct_name}`: field `{field_name}` "
                        f"of type `{field_type}` implements NoCopy and cannot be copied",
                        struct_info.line, struct_info.column,
                        hint="give the field a copyable type, or write copy() by hand"
                    )

    def _check_derivable_equals(self):
        """A struct/enum with a compiler-derived `==` (design 32) requires every
        field / payload to be Equatable, so the memberwise / payload-deep
        comparison is well-defined. Reports the first non-conforming member.
        Runs after all conformances are registered so field Equatable status is
        known regardless of declaration order."""
        for type_name in self._derived_equals_types:
            struct_info = self.namespace.structs.get(type_name)
            if struct_info is not None:
                for field_name, field_type in struct_info.fields.items():
                    if not self.namespace.is_equatable(field_type):
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"cannot derive `==` for `{type_name}`: field "
                            f"`{field_name}` of type `{field_type}` does not "
                            f"conform to `Equatable`",
                            struct_info.line, struct_info.column,
                            hint="give the field an Equatable type, or write "
                                 "`equals` by hand"
                        )
                        break
                continue
            enum_info = self.namespace.enums.get(type_name)
            if enum_info is not None:
                done = False
                for variant_name, fields in enum_info.variants.items():
                    for field_name, field_type in fields:
                        if not self.namespace.is_equatable(field_type):
                            self._error(
                                ErrorKind.TYPE_MISMATCH,
                                f"cannot derive `==` for `{type_name}`: payload "
                                f"`{field_name}` of variant `{variant_name}` has "
                                f"type `{field_type}` which does not conform to "
                                f"`Equatable`",
                                enum_info.ast_node.line if enum_info.ast_node else 0,
                                enum_info.ast_node.column if enum_info.ast_node else 0,
                                hint="give the payload an Equatable type"
                            )
                            done = True
                            break
                    if done:
                        break

    def _check_derivable_compare(self):
        """A struct/enum with a compiler-derived `compare` (design 48) requires
        every field / payload to be Comparable, so the lexicographic comparison
        is well-defined. Reports the first non-conforming member. Runs after all
        conformances are registered."""
        for type_name in self._derived_compare_types:
            struct_info = self.namespace.structs.get(type_name)
            if struct_info is not None:
                for field_name, field_type in struct_info.fields.items():
                    if not self.namespace.is_comparable(field_type):
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"cannot derive `compare` for `{type_name}`: field "
                            f"`{field_name}` of type `{field_type}` does not "
                            f"conform to `Comparable`",
                            struct_info.line, struct_info.column,
                            hint="give the field a Comparable type, or write "
                                 "`compare` by hand"
                        )
                        break
                continue
            enum_info = self.namespace.enums.get(type_name)
            if enum_info is not None:
                done = False
                for variant_name, fields in enum_info.variants.items():
                    for field_name, field_type in fields:
                        if not self.namespace.is_comparable(field_type):
                            self._error(
                                ErrorKind.TYPE_MISMATCH,
                                f"cannot derive `compare` for `{type_name}`: "
                                f"payload `{field_name}` of variant "
                                f"`{variant_name}` has type `{field_type}` which "
                                f"does not conform to `Comparable`",
                                enum_info.ast_node.line if enum_info.ast_node else 0,
                                enum_info.ast_node.column if enum_info.ast_node else 0,
                                hint="give the payload a Comparable type"
                            )
                            done = True
                            break
                    if done:
                        break

    def _check_derivable_hash(self):
        """A struct/enum with a compiler-derived `hash` (design 48) requires
        every field / payload to be Hashable. Reports the first non-conforming
        member. Runs after all conformances are registered."""
        for type_name in self._derived_hash_types:
            struct_info = self.namespace.structs.get(type_name)
            if struct_info is not None:
                for field_name, field_type in struct_info.fields.items():
                    if not self.namespace.is_hashable(field_type):
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"cannot derive `hash` for `{type_name}`: field "
                            f"`{field_name}` of type `{field_type}` does not "
                            f"conform to `Hashable`",
                            struct_info.line, struct_info.column,
                            hint="give the field a Hashable type, or write "
                                 "`hash` by hand"
                        )
                        break
                continue
            enum_info = self.namespace.enums.get(type_name)
            if enum_info is not None:
                done = False
                for variant_name, fields in enum_info.variants.items():
                    for field_name, field_type in fields:
                        if not self.namespace.is_hashable(field_type):
                            self._error(
                                ErrorKind.TYPE_MISMATCH,
                                f"cannot derive `hash` for `{type_name}`: payload "
                                f"`{field_name}` of variant `{variant_name}` has "
                                f"type `{field_type}` which does not conform to "
                                f"`Hashable`",
                                enum_info.ast_node.line if enum_info.ast_node else 0,
                                enum_info.ast_node.column if enum_info.ast_node else 0,
                                hint="give the payload a Hashable type"
                            )
                            done = True
                            break
                    if done:
                        break

    def _check_ord_hash_require_equatable(self):
        """Comparable and Hashable both REQUIRE Equatable (design 48): a type
        that conforms to either must already be Equatable, so `==` and the
        `compare`/`hash` results agree. Runs after all conformances are
        registered so auto-Equatable (POD) types satisfy the requirement without
        a redundant `extension T: Equatable {}`."""
        from ast_nodes import SawType, TypeKind

        def _type_of(name: str):
            if name in self.namespace.structs:
                return SawType(TypeKind.STRUCT, struct_name=name)
            if name in self.namespace.enums:
                return SawType(TypeKind.ENUM, enum_name=name)
            return None

        for type_name, trait in (
            [(n, "Comparable") for n in self._comparable_types]
            + [(n, "Hashable") for n in self._hashable_types]
        ):
            st = _type_of(type_name)
            if st is None:
                continue
            if not self.namespace.is_equatable(st):
                loc = self.namespace.structs.get(type_name) or self.namespace.enums.get(type_name)
                line = getattr(loc, 'line', 0)
                column = getattr(loc, 'column', 0)
                if line == 0 and getattr(loc, 'ast_node', None) is not None:
                    line, column = loc.ast_node.line, loc.ast_node.column
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`{type_name}` conforms to `{trait}` but not to `Equatable`: "
                    f"`{trait}` requires `Equatable`",
                    line, column,
                    hint=f"add `@synthesize extension {type_name}: Equatable {{}}`"
                )

    # design 128 removed `_check_deinit_containment`. Destruction is no longer
    # something a type has to opt into: a struct holding owning fields gets a
    # synthesized structural `deinit` (see `_synthesize_implicit_deinits`), and
    # codegen has always dropped such fields memberwise in reverse declaration
    # order. What a containing struct must still declare is its COPY policy —
    # the compiler knows how to destroy a value but not whether the author wants
    # it duplicated — which is what the three containment checks above enforce.

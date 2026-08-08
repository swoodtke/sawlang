"""
Type utility methods for the Saw type checker.

This module provides mixin methods for type resolution, compatibility checking,
and resource management trait detection (NoCopy, ImplicitCopy, Deinit).

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
    BindOptional, OptionalEvalExpr, ForceUnwrap
)
from errors import ErrorKind
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
        _is_implicit_copy_type: Check if type implements ImplicitCopy
        _is_deinit_type: Check if type implements Deinit
        _check_no_copy_return: Validate NoCopy types are moved when returned
        _check_integer_literal_range: Validate integer literal fits target type
        _check_no_copy_containment: Check structs with NoCopy fields implement NoCopy
        _check_implicit_copy_containment: Check structs with ImplicitCopy fields implement ImplicitCopy
        _check_deinit_containment: Check structs with Deinit fields implement Deinit
    """

    # =========================================================================
    # Namespace Lookup Helpers
    # =========================================================================

    def _canonical_type_name(self, name: str) -> str:
        """`name` as the module-qualified type IDENTITY it denotes here.

        Total (design 144): a name that denotes no type — a type parameter, a
        forward reference, an already-canonical identity — comes back
        unchanged, so callers canonicalize unconditionally."""
        ns = getattr(self, 'namespace', None)
        if ns is None or not name or '.' in name:
            return name
        return ns.resolve_type_identity(name)

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

    def _canonicalize_module_types(self, module_ast) -> None:
        """Rewrite every type REFERENCE in `module_ast` to its identity, in place.

        Design 144's central invariant is that a resolved type reference carries
        its identity, so codegen never re-resolves a name against a merged
        namespace where two `Header`s live. Annotations are the half that
        `_resolve_type` cannot reach on its own: a struct FIELD type, a method
        signature and a `let x: T` are read straight off the AST by the checks
        and by codegen, many without ever passing through resolution.

        In place, and by identity of the `SawType` OBJECT, because the symbol
        tables share those objects with the AST — `StructSymbol.fields` holds
        the very `SawType`s `struct.fields[i].type` does. Rewriting the object
        updates every holder at once, which is what makes the invariant hold
        without enumerating the holders.

        Runs per module, after that module's own types are registered (so its
        `type_names` view is complete) and before anything reads a signature.
        Idempotent: `resolve_type_identity` maps an identity to itself.
        """
        import dataclasses
        from ast_nodes import SawType as _SawType

        seen = set()

        def visit(obj):
            if obj is None or isinstance(obj, (str, int, float, bool)):
                return
            key = id(obj)
            if key in seen:
                return
            if isinstance(obj, _SawType):
                seen.add(key)
                if obj.struct_name:
                    obj.struct_name = self._canonical_type_name(obj.struct_name)
                if obj.enum_name:
                    obj.enum_name = self._canonical_type_name(obj.enum_name)
                if obj.existential_trait:
                    obj.existential_trait = self._canonical_type_name(
                        obj.existential_trait)
                for child in (obj.element_types, obj.inner_type, obj.type_args,
                              obj.array_element_type, obj.param_types,
                              obj.func_return_type):
                    visit(child)
                return
            if isinstance(obj, (list, tuple, set)):
                for item in obj:
                    visit(item)
                return
            if isinstance(obj, dict):
                for item in obj.values():
                    visit(item)
                return
            if dataclasses.is_dataclass(obj):
                seen.add(key)
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
                        canon = (self._canonical_type_name
                                 if _slot == "conformances"
                                 else self._canonical_trait_name)
                        setattr(obj, _slot, [canon(n) for n in names])
                for f in dataclasses.fields(obj):
                    if f.name in self._CANON_SKIP_FIELDS:
                        continue
                    visit(getattr(obj, f.name, None))
                return

        visit(module_ast)
        # A type alias resolved BEFORE this module's structs were registered
        # (aliases are registered first) can hold a rebuilt `SawType` that is
        # not in the AST, so it needs the walk explicitly.
        for type_def in getattr(module_ast, 'type_definitions', []):
            alias = self.namespace.lookup_type_alias(type_def.name)
            if alias is not None:
                visit(alias.aliased_type)
                visit(alias.immediate_type)

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
        # Local lookup
        result = self.namespace.lookup_struct(name)
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
        # Local lookup
        result = self.namespace.lookup_enum(name)
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
        result = self.namespace.lookup_trait(name)
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
        local = self.namespace.lookup_type_alias(name)
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
    # surface); Copy/ImplicitCopy/ExplicitCopy are Self-by-value anyway.
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
                    line, column)
            return

        if trait.name in reported:
            return

        def fail(msg, hint=None):
            reported.add(trait.name)
            self._error(ErrorKind.TYPE_MISMATCH,
                        f"cannot form `any {trait_name}`: {msg}", line, column,
                        hint=hint)

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
            for pt in (m.param_types or []):
                if pt is not None and self._names_self(pt):
                    fail(f"method `{mname}` takes `Self` by value "
                         f"(Self-by-value parameters are not object-safe)")
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
            hint="a type parameter's bound must name a trait that is in scope")

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

    def _resolve_type(self, saw_type: SawType) -> SawType:
        """Resolve user-defined types (ENUMs parsed as STRUCT).

        NOTE: Does NOT resolve type aliases because `type X = Y` creates a distinct type
        in Saw, not a transparent alias. Use _resolve_type_alias() when you need to
        check the underlying type structure (e.g., to check if something is Optional).
        """
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
                parts = struct_name.split('.')
                simple_name = parts[-1]
                module_parts = parts[:-1]

                # Walk the module path to find the final namespace
                current_ns = self.namespace
                for part in module_parts:
                    module_sym = current_ns.modules.get(part)
                    if module_sym and module_sym.namespace:
                        current_ns = module_sym.namespace
                    else:
                        current_ns = None
                        break

                if current_ns:
                    symbol = current_ns.resolve(
                        simple_name, check_visibility=True, accessor_module=self.namespace.module_path
                    )
                    if symbol:
                        # Design 144: the resolved reference carries the target's
                        # IDENTITY, not the spelling `mod.Type` was written with,
                        # so codegen never re-resolves a name it was handed.
                        identity = (getattr(symbol, 'type_identity', "")
                                    or simple_name)
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
        """
        table = getattr(self, '_const_static_decls', None)
        if table is None:
            table = {}
            self._const_static_decls = table
        for static in getattr(program, 'statics', []) or []:
            module = self._vis_module_for_source(
                getattr(static, 'source_file', None))
            # A duplicate is an error at registration; the FIRST declaration is
            # the one that survives it, so it is the one indexed here.
            table.setdefault((module, static.name),
                             self._static_const_binding(static))

    def _static_const_binding(self, static):
        """`(value, reason)` — the integer this `static` denotes in a constant
        position, or the reason it denotes none.

        The reason is phrased to complete "<reason> is not allowed here", and
        NAMES the static: the whole point of the rule is that a static may be
        written here now, so a refusal has to say which static and why rather
        than reading as "no static may".
        """
        from ast_nodes import IntLiteral, UnaryOp
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
        if isinstance(init, IntLiteral):
            return int(init.value), None
        if isinstance(init, UnaryOp) and init.op == '-' and \
                isinstance(init.operand, IntLiteral):
            return -int(init.operand.value), None
        return None, f"the computed static `{name}`"

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
            name, check_visibility=True, accessor_module=())

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
        elif t.kind in (TypeKind.STRUCT, TypeKind.ENUM):
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

    def _is_implicit_copy_type(self, saw_type: SawType) -> bool:
        """Check if a type implements ImplicitCopy."""
        if saw_type is None:
            return False

        # An escaping closure is a compiler-known ImplicitCopy value (design 73):
        # copying it retains a refcounted heap env, the last owner's drop tears it
        # down exactly once. A non-escaping closure is a borrow (owns nothing) and
        # is freely forwardable — not an ImplicitCopy transfer.
        if saw_type.kind == TypeKind.FUNCTION:
            return bool(getattr(saw_type, 'func_is_escaping', False))

        # A fixed array `[T; N]` inherits T's copy class (design 33): it is
        # ImplicitCopy iff its element type is (per-element implicit copy).
        if saw_type.kind == TypeKind.ARRAY:
            return self._is_implicit_copy_type(saw_type.array_element_type)

        # Get the type name for conformance lookup
        type_name = None
        if saw_type.kind == TypeKind.STRUCT:
            type_name = saw_type.struct_name
        elif saw_type.kind == TypeKind.ENUM:
            type_name = saw_type.enum_name
        elif saw_type.kind == TypeKind.STRING:
            # String is a compiler-known refcounted ImplicitCopy type.
            type_name = "String"

        if type_name is None:
            return False

        # Check if type conforms to ImplicitCopy
        return self.namespace.type_conforms_to(type_name, "ImplicitCopy")

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
        (Deinit / NoCopy / ImplicitCopy / ExplicitCopy). Such types auto-satisfy
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
        """Whether a concrete type satisfies the umbrella `Copy` bound:
        trivially copyable, or declaring ImplicitCopy / ExplicitCopy (or Copy).

        Delegates to the shared namespace helper so codegen agrees.
        """
        return self.namespace.type_satisfies_copy_bound(saw_type)

    def _is_deinit_type(self, saw_type: SawType) -> bool:
        """Check if a type implements Deinit (directly or through NoCopy/ImplicitCopy/ExplicitCopy)."""
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

        # Check if type conforms to Deinit (directly or via NoCopy/ImplicitCopy/ExplicitCopy)
        # NoCopy, ImplicitCopy and ExplicitCopy all inherit from Deinit
        return (self.namespace.type_conforms_to(type_name, "Deinit") or
                self.namespace.type_conforms_to(type_name, "NoCopy") or
                self.namespace.type_conforms_to(type_name, "ImplicitCopy") or
                self.namespace.type_conforms_to(type_name, "ExplicitCopy"))

    # Expression kinds that read a value out of *existing* owned storage,
    # as opposed to producing a freshly constructed temporary. Transferring
    # one of these leaves a live second owner behind, so these are exactly the
    # sites where NoCopy move-discipline must be enforced and ImplicitCopy
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
    # other read: trivial payloads copy bitwise, ImplicitCopy retains, and
    # ExplicitCopy/NoCopy refuse and name the three consuming spellings.
    # ------------------------------------------------------------------

    def _payload_read_policy(self, payload_type: Optional[SawType]) -> str:
        """The copy tier a payload read must honor: one of
        'trivial' / 'retain' / 'explicit' / 'nocopy'."""
        if payload_type is None:
            return 'trivial'
        # An opaque generic type parameter's tier is unknowable here, and each
        # instantiation decides it for itself. Keep the pre-131 bitwise read
        # rather than guess a retain that a `Vector` instantiation would turn
        # into a silent deep copy.
        if (payload_type.kind == TypeKind.STRUCT
                and payload_type.struct_name in getattr(self, 'current_type_params', {})):
            return 'trivial'
        if self._is_no_copy_type(payload_type):
            return 'nocopy'
        if self._is_explicit_copy_type(payload_type):
            return 'explicit'
        if self.namespace.is_trivially_copyable(payload_type):
            return 'trivial'
        # Everything left duplicates by RETAINING what it owns: an ImplicitCopy
        # value, an owning enum/optional/tuple/struct, an escaping closure env.
        return 'retain'

    def _check_payload_read(self, source: Optional[Expression],
                            payload_type: Optional[SawType],
                            node, context: str, line: int, column: int):
        """The value-read row for a payload extracted from `source`.

        `source` is the optional being read (the `if let` scrutinee, the `??`
        left operand); `node` is the AST node codegen will consult. A `move`
        source or a fresh temporary is already owned by the reader, so only a
        PLACE source is checked.
        """
        if source is None or not self._is_aliasing_expr(source):
            return
        # A `borrows` accessor's result is judged by the PLACE rule instead
        # (`place_uses._value_read_ok`), which knows the element type, the
        # receiver and which escape hatches that receiver actually publishes.
        # Both rules firing on one read is not a stricter check but a WRONG one:
        # `m["k"]` carries `place_struct` and is an `ArrayIndex`, so an
        # ImplicitCopy value got `payload_needs_copy` here AND `place_value_read`
        # there, and `let held = m["k"]!` retained twice against one release.
        # `v.get(i)!` never had the problem only because a MethodCall is not in
        # the aliasing set; the subscript spelling made the overlap reachable.
        if self._reads_a_place(source):
            return
        # A coroutine-frame field read carries the transform's own ownership
        # bookkeeping: a `move` read hands the frame's reference over through
        # `__saw_forget`, a non-`move` read is retained by codegen's frame-read
        # path (design 124), and a `self_opt` field IS the optional, drop flag
        # and all. The transform runs AFTER the type-check that already judged
        # these reads in their original, un-projected form, and the whole program
        # is then re-checked — so weighing in here would judge one read twice:
        # an ImplicitCopy payload would be retained a second time (a leak), and a
        # NoCopy payload the frame is legitimately moving out would be rejected.
        # (The mark rides the unwrap for a `o!` value read and the SOURCE for an
        # `if let` / `??` over a frame field.)
        if (getattr(node, 'frame_place_read', False)
                or getattr(source, 'frame_place_read', False)):
            return
        policy = self._payload_read_policy(payload_type)
        if policy == 'retain':
            node.payload_needs_copy = True
        elif policy in ('nocopy', 'explicit'):
            self._error(
                ErrorKind.CANNOT_COPY,
                f"cannot read the payload out of `{self._render_place(source)}` "
                f"in {context}: `{payload_type}` implements "
                f"{'NoCopy' if policy == 'nocopy' else 'ExplicitCopy'}",
                line, column,
                hint=self._payload_read_hint(source, policy)
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

    def _payload_read_hint(self, source: Expression, policy: str) -> str:
        """The consuming spellings a refused payload read can be rewritten to."""
        path = self._render_place(source)
        parts = []
        if policy == 'explicit':
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
        _, name, line, col = entry
        return name, line, col

    def _is_binding_moved(self, var_info) -> bool:
        return var_info.binding_id in self.moved_bindings

    def _mark_binding_moved(self, var_info, name: str, line: int, column: int):
        self.moved_bindings[var_info.binding_id] = (var_info, name, line, column)

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

    def _check_value_transfer(self, expr: Optional[Expression], target_type: Optional[SawType],
                              context: str, line: int, column: int,
                              is_return: bool = False):
        """Single checkpoint every copy/move site funnels through.

        Every site where a value is copied or moved into a new home (let/var
        initializers, assignment RHS, call arguments, returns, struct-field
        initializers, array/tuple elements, enum payloads) routes through here.
        It enforces NoCopy move-discipline and marks ImplicitCopy sites so codegen
        inserts `copy()` uniformly.

        Behavior by the source expression and its resolved type:
        - `move x`: ownership transfers; a transfer is neither a copy nor a
          NoCopy violation, so it is always accepted. The source binding's
          moved-from state is recorded in `_check_move_expr` (design 15), which
          runs for every `move` regardless of the enclosing transfer site.
        - by-reference argument (`&x` / `&var x`): NOT a transfer; skipped.
        - NoCopy type read from an existing binding (identifier / field access /
          index): an error -- it must be `move`d. A fresh temporary is fine.
        - ImplicitCopy type read from an existing binding: annotated
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
        # ImplicitCopy model surfaces (design 73).
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
        # structurally-ImplicitCopy enum, and left every OTHER wrapper (an
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

    def _build_access_path(self, expr: Expression):
        """Build an access path (root, projections) from an lvalue expression.

        root is a local/param name or 'self'. Each projection is one of
        ('field', name), ('tuple', int), or ('index', const_int | _DYNAMIC_INDEX).
        Returns None for a non-path expression (call result, literal, etc.) --
        those cannot legally appear under `&`/`&var` (rejected earlier by the
        lvalue check in `_check_reference_expr`).
        """
        projections = []
        node = expr
        while True:
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
        """
        # Validate that each reference argument's sigil matches its parameter.
        self._check_reference_sigils(values, param_types, param_names)
        # Each entry: (kind, path, name_expr, line, column) where kind is one of
        # 'mut', 'imm', 'moved'. name_expr renders the offending path.
        entries = []

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
                    entries.append(('mut' if spec.mode == 'ref_var' else 'imm',
                                    path, name_expr, spec.line, spec.column))

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
                else:
                    m_expr, m_line, m_col = ej, lj, cj
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
                # closures are ImplicitCopy, so a closure-bearing struct copies by
                # retaining the closure's env (handled like a String field below).
                if field_type is not None and field_type.kind == TypeKind.FUNCTION:
                    continue
                if self._is_no_copy_type(field_type):
                    self._error(
                        ErrorKind.CANNOT_COPY,
                        f"struct `{struct_name}` contains NoCopy field `{field_name}` of type `{field_type}` but does not implement NoCopy",
                        struct_info.line, struct_info.column,
                        hint=f"add `extension {struct_name}: NoCopy {{}}` — a "
                             f"NoCopy field makes `{struct_name}` move-only, and "
                             f"its `deinit` is synthesized"
                    )
                    break  # Only report once per struct

    def _check_implicit_copy_containment(self):
        """Check that structs containing ImplicitCopy fields also implement a copy policy."""
        for struct_name, struct_info in self.namespace.structs.items():
            # Skip if struct already declares a copy policy or NoCopy.
            # (NoCopy types can contain ImplicitCopy fields since they can't be
            # copied anyway; an ExplicitCopy struct copies the field explicitly
            # in its own copy().)
            if (self.namespace.type_conforms_to(struct_name, "ImplicitCopy") or
                self.namespace.type_conforms_to(struct_name, "ExplicitCopy") or
                self.namespace.type_conforms_to(struct_name, "NoCopy")):
                continue

            # Check each field
            for field_name, field_type in struct_info.fields.items():
                # String is a compiler-known ImplicitCopy value type; unlike a
                # user Rc it does not force containing structs to opt in (a plain
                # struct holding a String keeps the pre-refcount behavior:
                # bitwise field, no imposed copy/deinit policy). A fixed array of
                # String is exempt on the same footing (design 33): its per-element
                # retain/release is compiler-handled, so a `[String; N]` field does
                # not force a policy any more than a scalar `String` field does.
                if self._array_base_kind(field_type) == TypeKind.STRING:
                    continue
                # A closure field is a compiler-known ImplicitCopy value (design
                # 73), exactly like String: its refcounted-env retain/release is
                # compiler-handled, so it does not force the struct to opt into a
                # copy policy. (A struct copy retains the closure env; struct drop
                # releases it — exactly once at the last owner.)
                if field_type is not None and field_type.kind == TypeKind.FUNCTION:
                    continue
                if self._is_implicit_copy_type(field_type):
                    self._error(
                        ErrorKind.CANNOT_COPY,
                        f"struct `{struct_name}` contains ImplicitCopy field `{field_name}` of type `{field_type}` but does not implement ImplicitCopy",
                        struct_info.line, struct_info.column,
                        hint=f"add `@synthesize extension {struct_name}: "
                             f"ImplicitCopy {{}}` for a memberwise copy, or write "
                             f"`func copy(&self) -> {struct_name}` by hand"
                    )
                    break  # Only report once per struct

    def _check_explicit_copy_containment(self):
        """Check that structs containing ExplicitCopy fields declare ExplicitCopy or NoCopy."""
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
            # copied anyway.) ImplicitCopy is NOT sufficient: an ExplicitCopy
            # field cannot be cheaply/implicitly duplicated.
            if (self.namespace.type_conforms_to(struct_name, "ExplicitCopy") or
                self.namespace.type_conforms_to(struct_name, "NoCopy")):
                continue

            # Check each field
            for field_name, field_type in struct_info.fields.items():
                if self._is_explicit_copy_type(field_type):
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
        silently, and only for the ImplicitCopy case; a `Vector` or `File`
        payload got no tier at all and every transfer bitwise-aliased it.

        So the same question is now asked of enums, in the same words. Only the
        two OWNING tiers are demanded: an enum whose payloads are trivial or
        ImplicitCopy keeps working undeclared, exactly as a String-field struct
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
        """ImplicitCopy and ExplicitCopy are mutually exclusive on one type."""
        for struct_name in self.namespace.structs:
            if (self.namespace.type_conforms_to(struct_name, "ImplicitCopy") and
                self.namespace.type_conforms_to(struct_name, "ExplicitCopy")):
                struct_info = self.namespace.structs[struct_name]
                self._error(
                    ErrorKind.CANNOT_COPY,
                    f"type `{struct_name}` cannot implement both ImplicitCopy and ExplicitCopy",
                    struct_info.line, struct_info.column,
                    hint="pick one copy policy: ImplicitCopy (cheap, auto-invoked) or ExplicitCopy (deep, explicit `.copy()`)"
                )

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

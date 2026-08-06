"""
Saw Language Namespace
Unified symbol table for all declarations.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple, Set, Union
from enum import Enum, auto
from ast_nodes import SawType, TypeKind, Function, Struct, Enum as SawEnum, Extension, TypeParameter, Visibility


class SymbolKind(Enum):
    FUNCTION = auto()
    STRUCT = auto()
    ENUM = auto()
    METHOD = auto()
    TRAIT = auto()
    TYPE_ALIAS = auto()
    MODULE = auto()
    STATIC = auto()


# Symbol objects hold ONLY immutable declaration data. Builtin symbols (String,
# Vector, Result, ...) are shared BY REFERENCE into every module namespace via
# `Namespace.merge_into`, so any per-compilation mutable state written onto a
# symbol would alias across all module views. Per-compilation codegen artifacts
# therefore live in codegen-owned side tables keyed by canonical (mangled) name
# — `Codegen.struct_types` / `enum_types` / `functions` (see codegen/core.py) —
# never on these symbols. This keeps declaration symbols aliasing-safe and
# unblocks per-module / incremental codegen (design 27 item 1). Do not add
# codegen-populated fields here; extend the side tables instead.
@dataclass
class FunctionSymbol:
    """Symbol for a function or method."""
    kind: SymbolKind = SymbolKind.FUNCTION
    param_types: List[SawType] = field(default_factory=list)
    param_names: List[str] = field(default_factory=list)
    return_type: Optional[SawType] = None
    type_params: List[TypeParameter] = field(default_factory=list)
    default_values: List[Optional[Any]] = field(default_factory=list)
    is_static: bool = False
    is_init: bool = False
    self_mutable: bool = False
    self_is_reference: bool = True  # True for '&self' or '&var self'
    is_variadic: bool = False
    # design 22 effect system:
    #  - is_sync: declared `sync func` (body checked suspension-free)
    #  - is_blocking: `extern blocking func` (a suspension source)
    is_sync: bool = False
    is_blocking: bool = False
    # design 130: declared `unsafe func` / `unsafe init`. The declaration is the
    # obligation; the trigger rule checks it against the body.
    is_unsafe: bool = False
    visibility: Visibility = Visibility.PRIVATE
    # Member visibility (design 80): the module that DEFINES this method, for the
    # cross-module member-access gate. For std/builtin declarations this is a
    # synthetic per-file id (the prelude is merged into one AST for codegen, so
    # module_path alone cannot distinguish std from user code). Empty tuple = the
    # entry/user module in the non-module compilation path.
    def_module: Tuple[str, ...] = ()
    # True when this method satisfies a trait requirement of a conformed trait
    # (design 80): such a method is callable wherever the conformance is visible,
    # so it is exempt from the private-by-default method gate.
    satisfies_trait: bool = False
    # Type-param bounds from the enclosing extension, keyed by the extension's
    # type-param name (e.g. {"T": ["Copy"]} for `extension Vector<T: Copy>`).
    # A method with unmet bounds for a given instantiation does not exist there
    # (conditional conformance); the typechecker uses this to diagnose calls.
    extension_bounds: Dict[str, List[str]] = field(default_factory=dict)
    ast_node: Optional[Any] = None  # Function or Method AST node
    # Overloading (design 55): when a name carries 2+ overloads, the mangler
    # assigns each a type-signature-suffixed codegen symbol; `mangled_name` holds
    # it (empty for the common single-declaration case, where the plain name is
    # used). `decl_node` is the declaring AST Function/Method node, stamped with
    # the same `mangled_symbol` so codegen emits the definition under it.
    mangled_name: str = ""
    decl_node: Optional[Any] = None


@dataclass
class StructSymbol:
    """Symbol for a struct type."""
    kind: SymbolKind = SymbolKind.STRUCT
    fields: Dict[str, SawType] = field(default_factory=dict)
    field_order: List[str] = field(default_factory=list)
    type_params: List[TypeParameter] = field(default_factory=list)
    methods: Dict[str, FunctionSymbol] = field(default_factory=dict)
    # Overloading (design 55): name -> all overloads of that method. `methods`
    # keeps the first-registered overload as the representative (for the many
    # single-overload lookups); overloaded call sites resolve against this list.
    method_overloads: Dict[str, List[FunctionSymbol]] = field(default_factory=dict)
    init_methods: List[FunctionSymbol] = field(default_factory=list)
    conformances: List[str] = field(default_factory=list)
    visibility: Visibility = Visibility.PRIVATE
    # Member visibility (design 80): per-field visibility (name -> Visibility) and
    # the module that DEFINES this struct (for the cross-module field-access gate).
    # See FunctionSymbol.def_module for the std-synthetic-id rationale.
    field_visibility: Dict[str, Visibility] = field(default_factory=dict)
    def_module: Tuple[str, ...] = ()
    # Design 144: this type's IDENTITY — `(def_module, name)` fused into one
    # string (`Header$m$dep`), or the plain name for a root-module or std type.
    # It is the namespace key, the codegen layout key, the monomorphization
    # base and the method-mangling receiver; `type_identity.display_name`
    # recovers the short name for diagnostics and docs.
    type_identity: str = ""
    # `unsafe struct` (design 130): this type is unsafe, so naming/binding/
    # receiving/returning one of its values makes a function unsafe. Held here
    # rather than read off `ast_node`, which is None for a non-generic struct.
    is_unsafe: bool = False
    line: int = 0
    column: int = 0
    ast_node: Optional[Struct] = None
    # Specialized methods for specific type arguments (e.g., extension Vector<String>)
    # Key: tuple of type arg strings like ("String",), Value: method_name -> FunctionSymbol
    specialized_methods: Dict[Tuple[str, ...], Dict[str, FunctionSymbol]] = field(default_factory=dict)


@dataclass
class EnumSymbol:
    """Symbol for an enum type.

    Design 145: an enum carries METHODS on exactly the same terms as a struct —
    the method tables below mirror `StructSymbol`'s field for field, so every
    lookup, overload resolver and visibility gate written against a struct
    symbol works unchanged with an enum symbol. Enums had none of this, which is
    why `extension SysError { func describe(&self) ... }` was rejected and every
    error type in the tree became a struct to compensate.
    """
    kind: SymbolKind = SymbolKind.ENUM
    variants: Dict[str, List[Tuple[str, SawType]]] = field(default_factory=dict)
    variant_order: List[str] = field(default_factory=list)
    type_params: List[TypeParameter] = field(default_factory=list)
    visibility: Visibility = Visibility.PRIVATE
    # The module that DEFINES this enum. Read by the design-142 orphan rule (a
    # conformance is declarable only where the type or the trait is defined);
    # see FunctionSymbol.def_module for the std-synthetic-id rationale.
    def_module: Tuple[str, ...] = ()
    # Design 144: see StructSymbol.type_identity.
    type_identity: str = ""
    ast_node: Optional[SawEnum] = None
    # --- method surface, mirroring StructSymbol (design 145) ---
    methods: Dict[str, FunctionSymbol] = field(default_factory=dict)
    method_overloads: Dict[str, List[FunctionSymbol]] = field(default_factory=dict)
    # Enums have no `init` — the cases ARE the constructors (design 145 unit B),
    # so this stays empty and exists only to keep the struct-shaped code paths
    # uniform. `_register_extension` rejects an `init` with a teaching error.
    init_methods: List[FunctionSymbol] = field(default_factory=list)
    conformances: List[str] = field(default_factory=list)
    specialized_methods: Dict[Tuple[str, ...], Dict[str, FunctionSymbol]] = field(default_factory=dict)
    line: int = 0
    column: int = 0
    # Raw integer backing (design 145 unit B2): the declared backing type of a
    # payload-free enum (`enum E: UInt8 { ... }`), or None. When set, every case
    # carries an explicit value in `raw_values` and the enum is `as`-castable to
    # the backing with a synthesized `E.from(raw:)` inverse.
    raw_type: Optional[SawType] = None
    raw_values: Dict[str, int] = field(default_factory=dict)


@dataclass
class TraitMethodSymbol:
    """Symbol for a method signature in a trait."""
    name: str
    param_types: List[SawType] = field(default_factory=list)
    param_names: List[str] = field(default_factory=list)
    return_type: Optional[SawType] = None
    self_mutable: bool = False
    self_is_reference: bool = True
    # `sync` trait method (design 22/51): calls through `any` stay sync-callable.
    is_sync: bool = False
    # `unsafe` trait method (design 130): every conformer's implementation is
    # unsafe, and so is any call through the requirement.
    is_unsafe: bool = False
    # Default method body (design 56): the parsed `TraitMethod` AST when the
    # method declares a `{ ... }` default, else None. Carried so a conformer that
    # omits the method can synthesize a per-conformer Method from this body.
    ast_node: Optional[Any] = None


@dataclass
class TraitSymbol:
    """Symbol for a trait."""
    kind: SymbolKind = SymbolKind.TRAIT
    name: str = ""
    methods: Dict[str, TraitMethodSymbol] = field(default_factory=dict)
    associated_types: List[str] = field(default_factory=list)
    parent_traits: List[str] = field(default_factory=list)
    visibility: Visibility = Visibility.PRIVATE
    # The module that DEFINES this trait — the other place design 142's orphan
    # rule permits a conformance to be declared.
    def_module: Tuple[str, ...] = ()
    # Design 144: see StructSymbol.type_identity. A trait names a type in every
    # way that matters downstream — `any Trait` erasure, conformance tables and
    # vtable symbols are all keyed by it — so it qualifies on the same terms.
    type_identity: str = ""


@dataclass
class TypeAliasSymbol:
    """Symbol for a type alias."""
    kind: SymbolKind = SymbolKind.TYPE_ALIAS
    aliased_type: Optional[SawType] = None
    visibility: Visibility = Visibility.PRIVATE
    # Design 144: see StructSymbol.type_identity.
    type_identity: str = ""
    def_module: Tuple[str, ...] = ()
    # The UNRESOLVED immediate alias target (`type A = B` stores `B` verbatim,
    # possibly itself an alias). `aliased_type` collapses the whole chain to the
    # final underlying; `immediate_type` preserves one hop so the distinct-type
    # cast (design 63) can distinguish a partial projection toward an ancestor
    # alias (`b as A` where `type B = A`) from a sibling-alias cast.
    immediate_type: Optional[SawType] = None


@dataclass
class StaticSymbol:
    """Symbol for a module-level `static` declaration (design 41 + 149).

    Statics are const-initialized and immortal. An immutable one is Sync-only;
    an `unsafe static var` (design 149) is mutable, exempt from Sync, and makes
    every function that names it `unsafe` through the trigger rule.
    `mangled_name` is the codegen identity — the LLVM global's name, prefixed so
    it never clashes with a function of the same name in the (shared) LLVM value
    symbol table.
    """
    kind: SymbolKind = SymbolKind.STATIC
    type: Optional[SawType] = None
    mangled_name: str = ""
    visibility: Visibility = Visibility.PRIVATE
    # design 149: declared `unsafe static var`. Assignment, `&var` lends and
    # by-pointer receivers are permitted on one and refused on every other
    # static; naming one is unsafe contact.
    is_var: bool = False
    line: int = 0
    column: int = 0
    # The module that declared this static (DF-140h). A PRIVATE static in a
    # non-root module is nameable only from here, so it lives in the namespace's
    # per-module overlay rather than the shared simple-name slot.
    def_module: Tuple[str, ...] = ()


@dataclass
class ModuleSymbol:
    """Symbol for an imported or declared module."""
    kind: SymbolKind = SymbolKind.MODULE
    # The module's own namespace containing its symbols
    namespace: Optional['Namespace'] = None
    # Original module path (e.g., ["std", "io"])
    path: List[str] = field(default_factory=list)
    # Visibility of the module itself (public module vs module)
    visibility: Visibility = Visibility.PRIVATE


# Union type for any symbol that can be resolved
Symbol = Union[FunctionSymbol, StructSymbol, EnumSymbol, TraitSymbol, TypeAliasSymbol, ModuleSymbol, StaticSymbol]


class Namespace:
    """Unified symbol table for all declarations.

    This consolidates all type/function/method lookups into a single
    source of truth that both the type checker and code generator use.
    """

    def __init__(self, module_path: Tuple[str, ...] = ()):
        # Module path this namespace belongs to (e.g., ("modules", "utils"))
        self.module_path: Tuple[str, ...] = module_path

        # Package root for public(package) visibility (e.g., () for top-level)
        self.package_root: Tuple[str, ...] = ()

        # Core symbol tables
        self.functions: Dict[str, FunctionSymbol] = {}
        # Overloading (design 55): name -> all free-function overloads. The
        # `functions` map above keeps the first-registered overload as the
        # representative; overloaded call sites resolve against this list.
        self.function_overloads: Dict[str, List[FunctionSymbol]] = {}
        # Design 144: the four TYPE tables are keyed by module-qualified type
        # IDENTITY (`Header$m$dep`), not by the bare source name. Two modules'
        # private `Header`s are two entries, hence two layouts, two
        # monomorphizations and two method families. `type_names` below is the
        # name -> identity view a SOURCE reference resolves through.
        self.structs: Dict[str, StructSymbol] = {}
        self.enums: Dict[str, EnumSymbol] = {}
        self.traits: Dict[str, TraitSymbol] = {}
        self.type_aliases: Dict[str, TypeAliasSymbol] = {}
        self.modules: Dict[str, ModuleSymbol] = {}
        # Design 144: how a bare name spelled in THIS namespace's source
        # resolves. Keyed by the name as written — which is the declaration's
        # own name, or the local name an `import a.{Header as Hdr}` bound
        # (design 53 aliasing is a pure local rename, so the identity it maps
        # to is unchanged). Root-module and std types map a name to itself.
        self.type_names: Dict[str, str] = {}
        # Source label (module path string) each type name was first bound
        # from, and the names bound to two DIFFERENT identities. A bare
        # reference to an ambiguous name is the design-142 use-site error; the
        # binding stays first-wins so everything else behaves as before and the
        # diagnostic is raised once, where the author wrote the name.
        self.type_provenance: Dict[str, str] = {}
        self.ambiguous_types: Dict[str, Tuple[str, str, str]] = {}
        # Module-level `static` declarations (design 41), keyed by simple name.
        # Holds only the statics a simple name may legitimately resolve to from
        # ANY module: the public ones, plus the root module's own (which has no
        # module to qualify against). See `module_statics` for the rest.
        self.statics: Dict[str, StaticSymbol] = {}
        # DF-140h: module-PRIVATE statics of a non-root module, keyed by their
        # defining module then simple name. A private static is unnameable from
        # outside its module, so it must not occupy the shared `statics` slot —
        # doing so made every private constant in std (`ASCII_ZERO`, `SEEK_SET`,
        # `AF_UNIX`, ...) a reserved word for every program in the language.
        # Design 82 already gives each std FILE its own module identity; this is
        # the namespace half of that model, matching the codegen half DF-140f
        # landed for symbols.
        self.module_statics: Dict[Tuple[str, ...], Dict[str, StaticSymbol]] = {}

        # Type conformances: type_name -> {trait_name -> {assoc_type_name -> SawType}}
        self.conformances: Dict[str, Dict[str, Dict[str, SawType]]] = {}

        # Generic AST storage for instantiation
        self.generic_functions: Dict[str, Function] = {}
        self.generic_structs: Dict[str, Struct] = {}
        self.generic_enums: Dict[str, SawEnum] = {}
        self.generic_extensions: Dict[str, List[Extension]] = {}

        # Tracks which monomorphized instantiations have been generated
        self.instantiated: set = set()

        # Accessibility tracking for imports (Phase 2)
        # Symbols directly accessible without qualification
        self.directly_accessible: Set[str] = set()
        # If True, all symbols are accessible (legacy/non-module mode)
        self.allow_all_access: bool = True

        # Provenance for merge collision reporting: symbol name -> source label
        # (e.g. a module path string). Populated by merge_into when a source
        # label is supplied; used to name both sides of an ambiguity.
        self._provenance: Dict[str, str] = {}

    # =========================================================================
    # Unified Resolution
    # =========================================================================

    def resolve(self, path: str, check_access: bool = True,
                check_visibility: bool = False,
                accessor_module: Optional[Tuple[str, ...]] = None) -> Optional['Symbol']:
        """
        Resolve a symbol path to its definition.

        Handles both simple names ("Point") and qualified names ("utils.Point").

        Args:
            path: A symbol path, either simple ("foo") or dotted ("mod.foo")
            check_access: If True, verify the symbol is accessible (respects imports)
            check_visibility: If True, check visibility rules for cross-module access
            accessor_module: The module path of the code doing the lookup (for visibility)

        Returns:
            The resolved Symbol, or None if not found or not accessible
        """
        parts = path.split('.') if '.' in path else [path]
        return self._resolve_parts(parts, check_access, check_visibility, accessor_module)

    def _resolve_parts(self, parts: List[str], check_access: bool = True,
                       check_visibility: bool = False,
                       accessor_module: Optional[Tuple[str, ...]] = None) -> Optional['Symbol']:
        """Resolve a list of path components to a symbol.

        Args:
            parts: Path components to resolve
            check_access: If True, verify the symbol is directly accessible (import checking)
            check_visibility: If True, check visibility rules for cross-module access
            accessor_module: The module path of the code doing the lookup
        """
        if not parts:
            return None

        name = parts[0]
        remaining = parts[1:]

        # If there are remaining parts, first component must be a module
        if remaining:
            if name in self.modules:
                module = self.modules[name]
                # Check module visibility before allowing access
                if check_visibility and hasattr(module, 'visibility'):
                    acc_mod = accessor_module if accessor_module is not None else ()
                    if not self.check_visibility(
                        module.visibility,
                        symbol_module=self.module_path,
                        accessor_module=acc_mod,
                        package_root=self.package_root
                    ):
                        return None  # Module not visible
                if module.namespace:
                    # Cross-module access - check visibility with accessor context
                    return module.namespace._resolve_parts(
                        remaining, check_access=False, check_visibility=True,
                        accessor_module=accessor_module or self.module_path
                    )
            return None

        # Single name - check accessibility (import-based)
        if check_access and not self.allow_all_access:
            if name not in self.directly_accessible and name not in self.modules:
                # Name exists but isn't directly accessible
                return None

        # Helper to check visibility using proper module paths
        def is_visible(symbol) -> bool:
            if not check_visibility:
                return True
            if not hasattr(symbol, 'visibility'):
                return True
            # Use the full visibility checking with module paths
            acc_mod = accessor_module if accessor_module is not None else ()
            return self.check_visibility(
                symbol.visibility,
                symbol_module=self.module_path,
                accessor_module=acc_mod,
                package_root=self.package_root
            )

        # Check all symbol tables
        # Order: modules first (for qualified access), then types, then functions
        if name in self.modules:
            module = self.modules[name]
            # Check module visibility before returning
            if not is_visible(module):
                return None  # Module not visible from accessor
            return module

        for _table_lookup in (self.lookup_struct, self.lookup_enum,
                              self.lookup_trait, self.lookup_type_alias):
            sym = _table_lookup(name)
            if sym is not None:
                return sym if is_visible(sym) else None
        if name in self.functions:
            sym = self.functions[name]
            return sym if is_visible(sym) else None
        static_sym = self.get_static(name, accessor_module)
        if static_sym is not None:
            return static_sym if is_visible(static_sym) else None

        return None

    def make_accessible(self, name: str):
        """Mark a symbol as directly accessible (without qualification)."""
        self.directly_accessible.add(name)

    def make_all_accessible(self, names: List[str]):
        """Mark multiple symbols as directly accessible."""
        self.directly_accessible.update(names)

    def enable_import_checking(self):
        """Enable import-based accessibility checking."""
        self.allow_all_access = False

    def is_accessible(self, name: str) -> bool:
        """Check if a simple name is directly accessible."""
        if self.allow_all_access:
            return True
        return name in self.directly_accessible or name in self.modules

    def resolve_type(self, path: str) -> Optional['Symbol']:
        """Resolve a path that should be a type (struct, enum, or type alias)."""
        symbol = self.resolve(path)
        if symbol and symbol.kind in (SymbolKind.STRUCT, SymbolKind.ENUM, SymbolKind.TYPE_ALIAS):
            return symbol
        return None

    def resolve_callable(self, path: str) -> Optional['Symbol']:
        """Resolve a path that should be callable (function or struct init)."""
        symbol = self.resolve(path)
        if symbol and symbol.kind in (SymbolKind.FUNCTION, SymbolKind.STRUCT):
            return symbol
        return None

    # =========================================================================
    # Registration Methods
    # =========================================================================

    def register_function(self, name: str, symbol: FunctionSymbol):
        """Register a function symbol (design 55: appends to the overload set).

        The first registration under a name is also the representative in
        `self.functions`; later overloads only extend `function_overloads`.
        """
        self.function_overloads.setdefault(name, []).append(symbol)
        if name not in self.functions:
            self.functions[name] = symbol

    def lookup_function_overloads(self, name: str) -> List[FunctionSymbol]:
        """All free-function overloads registered under `name` (design 55)."""
        return self.function_overloads.get(name, [])

    @staticmethod
    def _static_is_module_local(symbol: 'StaticSymbol') -> bool:
        """Whether `symbol` belongs in the per-module overlay rather than the
        shared simple-name slot (DF-140h): a PRIVATE static of a non-root
        module, which no other module can name."""
        return (symbol.visibility == Visibility.PRIVATE
                and bool(getattr(symbol, 'def_module', ()) or ()))

    def register_static(self, name: str, symbol: 'StaticSymbol'):
        """Register a module-level static symbol (design 41).

        A module-private static goes to its own module's overlay; everything
        else takes the shared slot (DF-140h)."""
        if self._static_is_module_local(symbol):
            key = tuple(symbol.def_module)
            self.module_statics.setdefault(key, {})[name] = symbol
        else:
            self.statics[name] = symbol

    def has_static(self, name: str,
                   module: Optional[Tuple[str, ...]] = None) -> bool:
        """Whether a static named `name` is visible to code in `module`."""
        return self.get_static(name, module) is not None

    def get_static(self, name: str,
                   module: Optional[Tuple[str, ...]] = None
                   ) -> Optional['StaticSymbol']:
        """Look up a static by simple name, as seen from `module`.

        The accessor module's OWN private statics win over the shared slot, so a
        std file keeps reading its own `ASCII_ZERO` even when the program being
        compiled declares one too (DF-140h)."""
        own = self.module_statics.get(tuple(module or ()))
        if own is not None and name in own:
            return own[name]
        return self.statics.get(name)

    # =========================================================================
    # Type registration and name binding (design 144)
    #
    # Two separate acts, and keeping them separate is the whole point:
    #   1. The symbol is stored under its IDENTITY. Two modules' `Header`s are
    #      two entries that can never overwrite each other.
    #   2. The name as WRITTEN is bound to that identity in this namespace's
    #      `type_names` view. That binding is per-namespace, so `Header` means
    #      dep's Header inside dep and the entry's Header inside the entry.
    # =========================================================================

    @staticmethod
    def _identity_of(name: str, symbol) -> str:
        """`symbol`'s identity, defaulting to the name it is registered under.

        The default covers every symbol built outside the typechecker's
        registration pass — builtins, the module-AST shim below — none of which
        belongs to a qualifying module."""
        return getattr(symbol, 'type_identity', "") or name

    def bind_type_name(self, local: str, identity: str, category: str = "type",
                       source_label: Optional[str] = None):
        """Bind the source-visible name `local` to `identity` here.

        First-wins, matching every other binding in this namespace. A second
        binding to a DIFFERENT identity is recorded in `ambiguous_types` rather
        than dropped silently: the name is genuinely ambiguous at any bare use,
        which is the design-142 use-site error, raised once where it is written.
        """
        prev = self.type_names.get(local)
        if prev is None:
            self.type_names[local] = identity
            if source_label is not None:
                self.type_provenance[local] = source_label
            return
        if prev == identity or local in self.ambiguous_types:
            return
        self.ambiguous_types[local] = (
            category,
            self.type_provenance.get(local, "<unknown>"),
            source_label if source_label is not None else "<unknown>",
        )

    def register_struct(self, name: str, symbol: StructSymbol,
                        source_label: Optional[str] = None):
        """Register a struct symbol under its identity, bound to `name`."""
        identity = self._identity_of(name, symbol)
        self.structs[identity] = symbol
        self.bind_type_name(name, identity, "struct", source_label)

    def register_enum(self, name: str, symbol: EnumSymbol,
                      source_label: Optional[str] = None):
        """Register an enum symbol under its identity, bound to `name`."""
        identity = self._identity_of(name, symbol)
        self.enums[identity] = symbol
        self.bind_type_name(name, identity, "enum", source_label)

    def register_trait(self, name: str, symbol: TraitSymbol,
                       source_label: Optional[str] = None):
        """Register a trait symbol under its identity, bound to `name`."""
        identity = self._identity_of(name, symbol)
        self.traits[identity] = symbol
        self.bind_type_name(name, identity, "trait", source_label)

    def register_type_alias(self, name: str, symbol: TypeAliasSymbol,
                            source_label: Optional[str] = None):
        """Register a type alias symbol under its identity, bound to `name`."""
        identity = self._identity_of(name, symbol)
        self.type_aliases[identity] = symbol
        self.bind_type_name(name, identity, "type alias", source_label)

    def _iter_types(self, table: Dict[str, Any]):
        """`(source name, identity, symbol)` for every type nameable here.

        Iterating the table directly would yield IDENTITIES, which is the wrong
        key for anything that re-binds a name in another namespace (an import
        binds `Header`, never `Header$m$dep`). Iterating `type_names` gives the
        spellings, one entry per way the type can be written here."""
        for name, identity in list(self.type_names.items()):
            sym = table.get(identity)
            if sym is not None:
                yield name, identity, sym

    def iter_structs(self):
        return self._iter_types(self.structs)

    def iter_enums(self):
        return self._iter_types(self.enums)

    def iter_traits(self):
        return self._iter_types(self.traits)

    def resolve_type_identity(self, name: str) -> str:
        """The identity a bare `name` refers to here, or `name` itself.

        Total by design: an unknown name resolves to itself, so every caller
        that only wants to canonicalize can call this unconditionally."""
        if not name:
            return name
        return self.type_names.get(name, name)

    def register_module(self, alias: str, symbol: ModuleSymbol):
        """Register a module symbol (for imports)."""
        self.modules[alias] = symbol

    def register_module_from_ast(self, alias: str, module_ast: 'Program', path: List[str] = None,
                                  visibility: Visibility = Visibility.PUBLIC,
                                  module_map: dict = None):
        """
        Create and register a module from a parsed AST.

        This builds a namespace from the module's declarations and registers
        it under the given alias.

        Args:
            alias: The local name for the module (e.g., "utils")
            module_ast: The parsed Program AST for the module
            path: The original module path (e.g., ["modules", "utils"])
            visibility: The visibility of the module itself (PUBLIC for imports,
                       depends on declaration for module declarations)
            module_map: Dict of module_path_tuple -> AST for resolving imports
        """
        # Create a namespace for the module with its path
        mod_path = tuple(path) if path else ()
        mod_ns = Namespace(module_path=mod_path)
        mod_ns.package_root = self.package_root  # Inherit package root

        # Register all symbols from the module AST
        for struct in module_ast.structs:
            fields = {f.name: f.type for f in struct.fields}
            field_order = [f.name for f in struct.fields]
            mod_ns.register_struct(struct.name, StructSymbol(
                fields=fields,
                field_order=field_order,
                type_params=struct.type_params,
                visibility=struct.visibility,
                is_unsafe=getattr(struct, 'is_unsafe', False),
                line=struct.line,
                column=struct.column,
                ast_node=struct if struct.type_params else None
            ))

        for enum in module_ast.enums:
            variants = {}
            variant_order = []
            for variant in enum.variants:
                variant_order.append(variant.name)
                variants[variant.name] = [(at.name, at.type) for at in variant.associated_types]
            mod_ns.register_enum(enum.name, EnumSymbol(
                variants=variants,
                variant_order=variant_order,
                type_params=enum.type_params,
                visibility=enum.visibility,
                ast_node=enum if enum.type_params else None
            ))

        for func in module_ast.functions:
            param_types = [p.type for p in func.parameters]
            param_names = [p.name for p in func.parameters]
            mod_ns.register_function(func.name, FunctionSymbol(
                param_types=param_types,
                param_names=param_names,
                return_type=func.return_type,
                type_params=func.type_params,
                visibility=func.visibility,
                is_unsafe=getattr(func, 'is_unsafe', False),
                ast_node=func if func.type_params else None
            ))

        for trait in module_ast.traits:
            methods = {}
            assoc_types = []
            for m in trait.methods:
                methods[m.name] = TraitMethodSymbol(
                    name=m.name,
                    param_types=[p.type for p in m.parameters],
                    param_names=[p.name for p in m.parameters],
                    return_type=m.return_type,
                    self_mutable=m.self_mutable
                )
            for at in trait.associated_types:
                assoc_types.append(at.name)
            mod_ns.register_trait(trait.name, TraitSymbol(
                methods=methods,
                associated_types=assoc_types,
                visibility=trait.visibility
            ))

        # Register inline module declarations (submodules)
        # Only PUBLIC modules are visible to importers of this module
        for mod_decl in getattr(module_ast, 'module_decls', []):
            if mod_decl.is_inline and mod_decl.body:
                # Determine visibility for the submodule
                submod_visibility = Visibility.PUBLIC if mod_decl.is_public else Visibility.PRIVATE
                # Recursively register the inline module in this module's namespace
                submod_path = list(mod_path) + [mod_decl.name] if mod_path else [mod_decl.name]
                mod_ns.register_module_from_ast(
                    mod_decl.name,
                    mod_decl.body,
                    submod_path,
                    visibility=submod_visibility,
                    module_map=module_map
                )

        # Register the module's own imports in its namespace (Phase 4.5)
        # This allows the module's code to resolve its import references
        # Note: These imports are PRIVATE - not exposed to importers of this module
        if module_map:
            for imp in getattr(module_ast, 'imports', []):
                imp_path = tuple(imp.path)
                if imp_path in module_map:
                    imp_alias = imp.alias or imp.path[-1]
                    mod_ns.register_module_from_ast(
                        imp_alias,
                        module_map[imp_path],
                        list(imp_path),
                        visibility=Visibility.PRIVATE,  # Imports are private
                        module_map=module_map
                    )

        # Create and register the module symbol
        self.modules[alias] = ModuleSymbol(
            namespace=mod_ns,
            path=path or [],
            visibility=visibility
        )

    def method_owner(self, type_name: str):
        """The symbol that carries methods for `type_name` — a struct or, since
        design 145, an enum. Enums grew the same method tables, so every caller
        below is written once against whichever owns the name."""
        owner = self.lookup_struct(type_name)
        if owner is not None:
            return owner
        return self.lookup_enum(type_name)

    def register_method(self, struct_name: str, method_name: str, symbol: FunctionSymbol):
        """Register a method on a struct or enum (design 55: appends to the
        overload set).

        The first registration under a name is the representative in `methods`;
        later overloads only extend `method_overloads`.
        """
        s = self.method_owner(struct_name)
        if s is not None:
            s.method_overloads.setdefault(method_name, []).append(symbol)
            if method_name not in s.methods:
                s.methods[method_name] = symbol

    def lookup_method_overloads(self, struct_name: str, method_name: str) -> List[FunctionSymbol]:
        """All overloads of `method_name` on `struct_name` (design 55)."""
        owner = self.method_owner(struct_name)
        if owner:
            return owner.method_overloads.get(method_name, [])
        return []

    def register_init_method(self, struct_name: str, symbol: FunctionSymbol):
        """Register an init method on a struct."""
        owner = self.lookup_struct(struct_name)
        if owner is not None:
            owner.init_methods.append(symbol)

    def register_specialized_method(self, struct_name: str, spec_key: Tuple[str, ...],
                                     method_name: str, method: FunctionSymbol):
        """Register a specialized method for a generic struct or enum
        instantiation.

        Args:
            struct_name: The base type name (e.g., "Vector")
            spec_key: Tuple of type argument strings (e.g., ("String",))
            method_name: The method name
            method: The FunctionSymbol for the method
        """
        owner = self.method_owner(struct_name)
        if owner:
            if spec_key not in owner.specialized_methods:
                owner.specialized_methods[spec_key] = {}
            owner.specialized_methods[spec_key][method_name] = method

    def register_conformance(self, type_name: str, trait_name: str,
                            type_assignments: Optional[Dict[str, SawType]] = None):
        """Register that a type conforms to a trait."""
        if type_name not in self.conformances:
            self.conformances[type_name] = {}
        self.conformances[type_name][trait_name] = type_assignments or {}

        # Also add to the type's own conformance list (struct or, since design
        # 145, enum — both carry one).
        owner = self.method_owner(type_name)
        if owner is not None:
            if trait_name not in owner.conformances:
                owner.conformances.append(trait_name)

    # =========================================================================
    # Lookup Methods
    # =========================================================================

    def lookup_function(self, name: str) -> Optional[FunctionSymbol]:
        """Look up a function by name."""
        return self.functions.get(name)

    def _lookup_type(self, table: Dict[str, Any], name: str):
        """Look a type up in `table` by IDENTITY or by source name (design 144).

        The identity hit comes first: everything downstream of type checking
        (codegen keys, monomorphization, mangling) holds identities, and for an
        unqualified type the two spellings coincide anyway."""
        sym = table.get(name)
        if sym is not None:
            return sym
        identity = self.type_names.get(name)
        if identity is not None and identity != name:
            return table.get(identity)
        return None

    def lookup_struct(self, name: str) -> Optional[StructSymbol]:
        """Look up a struct by identity or source name."""
        return self._lookup_type(self.structs, name)

    def lookup_enum(self, name: str) -> Optional[EnumSymbol]:
        """Look up an enum by identity or source name."""
        return self._lookup_type(self.enums, name)

    def lookup_trait(self, name: str) -> Optional[TraitSymbol]:
        """Look up a trait by identity or source name."""
        return self._lookup_type(self.traits, name)

    def lookup_type_alias(self, name: str) -> Optional[TypeAliasSymbol]:
        """Look up a type alias by identity or source name."""
        return self._lookup_type(self.type_aliases, name)

    def lookup_method(self, struct_name: str, method_name: str) -> Optional[FunctionSymbol]:
        """Look up a method on a struct or enum (design 145)."""
        owner = self.method_owner(struct_name)
        if owner:
            return owner.methods.get(method_name)
        return None

    def lookup_specialized_method(self, struct_name: str, spec_key: Tuple[str, ...],
                                   method_name: str) -> Optional[FunctionSymbol]:
        """Look up a specialized method for a generic struct instantiation.

        Args:
            struct_name: The base struct name (e.g., "Vector")
            spec_key: Tuple of type argument strings (e.g., ("String",))
            method_name: The method name

        Returns:
            The FunctionSymbol if found, None otherwise
        """
        owner = self.method_owner(struct_name)
        if owner and spec_key in owner.specialized_methods:
            return owner.specialized_methods[spec_key].get(method_name)
        return None

    def lookup_type(self, name: str) -> Optional[SawType]:
        """Resolve a type name to its SawType."""
        # Check type aliases first
        alias = self.lookup_type_alias(name)
        if alias is not None and alias.aliased_type:
            return alias.aliased_type
        # Check structs / enums. The built type carries the IDENTITY, not the
        # spelling (design 144) — everything downstream keys on it.
        struct = self.lookup_struct(name)
        if struct is not None:
            return SawType(kind=TypeKind.STRUCT,
                           struct_name=self._identity_of(name, struct))
        enum = self.lookup_enum(name)
        if enum is not None:
            return SawType(kind=TypeKind.ENUM,
                           enum_name=self._identity_of(name, enum))
        return None

    # =========================================================================
    # Query Methods
    # =========================================================================

    def get_return_type(self, func_name: str) -> Optional[SawType]:
        """Get the return type of a function."""
        func = self.functions.get(func_name)
        return func.return_type if func else None

    def get_method_return_type(self, struct_name: str, method_name: str) -> Optional[SawType]:
        """Get the return type of a method."""
        method = self.lookup_method(struct_name, method_name)
        return method.return_type if method else None

    def is_static_method(self, struct_name: str, method_name: str) -> bool:
        """Check if a method is static."""
        method = self.lookup_method(struct_name, method_name)
        return method.is_static if method else False

    def is_init_method(self, struct_name: str, method_name: str) -> bool:
        """Check if a method is an init method."""
        method = self.lookup_method(struct_name, method_name)
        return method.is_init if method else False

    def type_conforms_to(self, type_name: str, trait_name: str, _visiting=None) -> bool:
        """Check if a type conforms to a trait.

        Checks this namespace, then any imported module namespace (conformances
        are registered per-module at typecheck time and only merged for codegen,
        so a cross-module query — e.g. a manifest module erasing a TomlError from
        the toml module — must look through imports too, design 56). The visited
        set guards against import cycles."""
        if type_name in self.conformances and trait_name in self.conformances[type_name]:
            return True
        if _visiting is None:
            _visiting = set()
        # `id()` here is a within-one-query cycle guard over Namespace objects,
        # not the persistent node identity design 126 R2 replaced: the set dies
        # with the recursion and must compare physical objects.
        _visiting.add(id(self))
        for module_sym in self.modules.values():
            ns = getattr(module_sym, 'namespace', None)
            if ns is not None and id(ns) not in _visiting:
                if ns.type_conforms_to(type_name, trait_name, _visiting):
                    return True
        return False

    def get_conformances(self, type_name: str) -> List[str]:
        """Get all traits a type conforms to."""
        if type_name not in self.conformances:
            return []
        return list(self.conformances[type_name].keys())

    # =========================================================================
    # Copy-family bound satisfaction (shared by typechecker and codegen)
    #
    # These are the single source of truth for "does a concrete type satisfy a
    # `Copy`-family bound". Both the typechecker (bound-checking on calls) and
    # codegen (skipping unsatisfied bounded-extension instantiations) call them,
    # so the two phases can never disagree about whether e.g. `Vector<File>`'s
    # conditional `copy()` exists.
    # =========================================================================

    _TRIVIAL_PRIMITIVE_KINDS = frozenset({
        TypeKind.INT, TypeKind.UINT,
        TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
        TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64,
        TypeKind.FLOAT, TypeKind.BOOL,
    })

    # Primitive kinds that register an extensible pseudo-struct (design 57), so a
    # `extension Int: Fooable` conformance is keyed under this name — the same key
    # trait-method dispatch resolves a primitive receiver's methods by.
    _PRIMITIVE_CONFORMANCE_KEYS = {
        TypeKind.INT: "Int",
        TypeKind.FLOAT: "Float",
    }

    def _lookup_struct_deep(self, name: str) -> Optional[StructSymbol]:
        """Look up a struct in this namespace or any imported module namespace."""
        result = self.lookup_struct(name)
        if result:
            return result
        for module_sym in self.modules.values():
            if module_sym.namespace:
                found = module_sym.namespace._lookup_struct_deep(name)
                if found:
                    return found
        return None

    def _lookup_type_alias_deep(self, name: str) -> Optional[TypeAliasSymbol]:
        """Look up a type alias in this namespace or any imported module namespace."""
        result = self.lookup_type_alias(name)
        if result:
            return result
        for module_sym in self.modules.values():
            if module_sym.namespace:
                found = module_sym.namespace._lookup_type_alias_deep(name)
                if found:
                    return found
        return None

    def is_trivially_copyable(self, saw_type: SawType) -> bool:
        """A type is trivially copyable iff it can be duplicated bitwise: all
        fields are trivially copyable, and it declares no resource trait
        (Deinit / NoCopy / ImplicitCopy / ExplicitCopy). Such types auto-satisfy
        `Copy`; `.copy()` on them lowers to a bitwise copy.
        """
        if saw_type is None:
            return False
        kind = saw_type.kind
        if kind in self._TRIVIAL_PRIMITIVE_KINDS:
            return True
        if kind == TypeKind.TUPLE:
            return all(self.is_trivially_copyable(e) for e in (saw_type.element_types or []))
        if kind == TypeKind.OPTIONAL:
            return saw_type.inner_type is not None and self.is_trivially_copyable(saw_type.inner_type)
        if kind == TypeKind.ARRAY:
            # A fixed array `[T; N]` inherits T's copy class (design 33): it is
            # trivially copyable iff its element type is.
            return (saw_type.array_element_type is not None
                    and self.is_trivially_copyable(saw_type.array_element_type))
        if kind == TypeKind.STRUCT:
            name = saw_type.struct_name
            # A type alias flows to its underlying type for triviality.
            alias_sym = self._lookup_type_alias_deep(name)
            if alias_sym and alias_sym.aliased_type:
                return self.is_trivially_copyable(alias_sym.aliased_type)
            # Any declared resource trait disqualifies triviality.
            if (self.type_conforms_to(name, "Deinit") or
                self.type_conforms_to(name, "NoCopy") or
                self.type_conforms_to(name, "ImplicitCopy") or
                self.type_conforms_to(name, "ExplicitCopy")):
                return False
            struct_sym = self._lookup_struct_deep(name)
            if struct_sym is None:
                # Unknown / opaque type parameter: not known to be trivial.
                return False
            return all(self.is_trivially_copyable(ft) for ft in struct_sym.fields.values())
        if kind == TypeKind.ENUM:
            # A PAYLOAD-FREE enum is a bare tag: it owns nothing, so a copy is
            # bitwise and there is no deinit to double-run. This branch used to
            # be missing entirely, so `Color` fell off the end as False and the
            # Map/Set key check reported the false reason "owns a Deinit without
            # a copy (it is move-only, not retainable)" for a type that owns
            # nothing (design 132 unit E / DF-128b). The gate matches
            # `is_equatable`'s auto-conformance exactly, which is what the spec
            # promises: the auto-Copy set and the auto-Equatable set are one set.
            # An enum carrying a payload keeps the old answer — its tier is
            # derived structurally by `is_implicit_copy_enum` and the
            # fall-through paths, and widening that is a separate question.
            name = saw_type.enum_name
            if name is None:
                return False
            if (self.type_conforms_to(name, "Deinit") or
                    self.type_conforms_to(name, "NoCopy") or
                    self.type_conforms_to(name, "ImplicitCopy") or
                    self.type_conforms_to(name, "ExplicitCopy")):
                return False
            enum_sym = self._lookup_enum_deep(name)
            if enum_sym is None:
                return False
            return all(len(fields) == 0 for fields in enum_sym.variants.values())
        return False

    def type_satisfies_copy_bound(self, saw_type: SawType) -> bool:
        """Whether a concrete type satisfies the umbrella `Copy` bound:
        trivially copyable, or declaring ImplicitCopy / ExplicitCopy (or Copy)."""
        if saw_type is None:
            return False
        if self.is_trivially_copyable(saw_type):
            return True
        # An escaping closure IS ImplicitCopy (design 73): copying it retains the
        # refcounted heap env (a no-op on a null env). It satisfies the umbrella
        # `Copy` bound so `Vector<() -> Int>.copy()`/`.get()` work — codegen routes
        # every element copy through the closure-env retain glue (design 77 item 3).
        # Any function TYPE used as a stored value (a container element, a struct
        # field) is escaping; the `escaping` bit is a typechecker resolution
        # artifact not always present on the codegen-side type arg, so accept the
        # FUNCTION kind uniformly (a non-escaping closure is parameter-only and
        # never reaches this Copy-bound machinery).
        if saw_type.kind == TypeKind.FUNCTION:
            return True
        # A fixed array `[T; N]` inherits T's copy class (design 33): it
        # satisfies `Copy` iff its element type does.
        if saw_type.kind == TypeKind.ARRAY:
            return (saw_type.array_element_type is not None
                    and self.type_satisfies_copy_bound(saw_type.array_element_type))
        name = None
        if saw_type.kind == TypeKind.STRUCT:
            name = saw_type.struct_name
        elif saw_type.kind == TypeKind.ENUM:
            name = saw_type.enum_name
        elif saw_type.kind == TypeKind.STRING:
            name = "String"
        if name is None:
            return False
        return (self.type_conforms_to(name, "ImplicitCopy") or
                self.type_conforms_to(name, "ExplicitCopy") or
                self.type_conforms_to(name, "Copy"))

    # =========================================================================
    # The copy tier (design 139) — one transfer class per type.
    #
    # Every type answers with exactly one tier, and every read consults it.
    # Ordered by how much ceremony a transfer costs, weakest first:
    #
    #   'free'      the compiler handles the transfer with no ceremony from the
    #               author — a POD bitwise copy, or an owning aggregate whose
    #               retain codegen inserts on its own (an undeclared struct with
    #               a String field).
    #   'implicit'  duplicated by a refcount retain at every transfer.
    #   'explicit'  never duplicated implicitly: `move`, or a visible `.copy()`.
    #   'nocopy'    move-only.
    #   'abstract'  DEMANDS A BOUND — the written type mentions an opaque type
    #               PARAMETER, so its transfer class is a property of the
    #               INSTANTIATION and cannot be read off the declaration. It
    #               joins as the strongest tier because the unknown may be
    #               move-only. Sites that must decide before monomorphization
    #               (a place value read) answer it from the parameter's BOUNDS
    #               and error eagerly when the bounds do not prove a copy;
    #               sites that emit at the instantiation substitute first and
    #               never see this answer (design 146, DF-146e).
    #
    # A WRAPPER is never weaker than what it wraps: an `Optional<T>`, a tuple, a
    # fixed array, and an enum's payloads all JOIN their parts' tiers. That join
    # is what closes DF-131a. Before design 139 `Optional<T>` had no tier at all
    # — the checkpoint keyed every predicate off a struct/enum NAME, and an
    # optional has neither — so a whole-optional read of a move-only payload fell
    # past every arm to a silent bitwise alias that double-dropped.
    #
    # A DECLARED conformance WINS over the structural join, which is what makes a
    # user enum's policy its author's choice rather than something inferred out
    # from under them. Registration refuses a bare enum whose join is 'explicit'
    # or 'nocopy', so by the time this runs a declaration is always present where
    # one is owed.
    # =========================================================================

    _COPY_TIER_ORDER = ('free', 'implicit', 'explicit', 'nocopy', 'abstract')

    # Names that reach the type predicates as a STRUCT-kinded SawType even
    # though they are compiler-known types, not type parameters. The parser
    # defaults an unknown capitalized name to STRUCT, so the "resolves to no
    # declaration" test that identifies a type parameter needs them excluded.
    _BUILTIN_TYPE_NAMES = frozenset({
        "String", "Int", "UInt", "Float", "Bool", "Void", "Never", "Self",
        "Int8", "Int16", "Int32", "Int64",
        "UInt8", "UInt16", "UInt32", "UInt64",
    })

    def _tier_join(self, a: str, b: str) -> str:
        """The stronger of two tiers — a composite is never weaker than a part."""
        order = self._COPY_TIER_ORDER
        return a if order.index(a) >= order.index(b) else b

    def is_abstract_type_name(self, name: str) -> bool:
        """True when `name` is an opaque type PARAMETER rather than a declared
        type. A type parameter reaches here as a STRUCT-kinded SawType carrying
        its own name (`SawType.substitute` keys off exactly that), so the test
        is whether the name resolves to any declaration at all — the same
        "opaque / unresolved type parameter" reading `_send_sync` uses."""
        if name is None or name in self._BUILTIN_TYPE_NAMES:
            return False
        return (self._lookup_struct_deep(name) is None
                and self._lookup_enum_deep(name) is None
                and self._lookup_type_alias_deep(name) is None)

    def _has_abstract_type_arg(self, saw_type: SawType) -> bool:
        """Does any type ARGUMENT of this instantiation mention a parameter?"""
        return any(self.copy_tier(arg) == 'abstract'
                   for arg in (saw_type.type_args or [])
                   if arg is not None)

    def declared_copy_tier(self, type_name: str) -> str:
        """The tier a type NAME declares, or 'free' when it declares none."""
        if self.type_conforms_to(type_name, "NoCopy"):
            return 'nocopy'
        if self.type_conforms_to(type_name, "ExplicitCopy"):
            return 'explicit'
        if self.type_conforms_to(type_name, "ImplicitCopy"):
            return 'implicit'
        return 'free'

    def copy_tier(self, saw_type: SawType, _visiting=None) -> str:
        """The single transfer class of `saw_type` (design 139)."""
        if saw_type is None:
            return 'free'
        saw_type = self._normalize_struct_enum(saw_type)
        kind = saw_type.kind
        if kind == TypeKind.FUNCTION:
            # An escaping closure carries a refcounted heap env (design 73) and
            # copies by retaining it; a non-escaping one borrows and owns nothing.
            return 'implicit' if getattr(saw_type, 'func_is_escaping', False) else 'free'
        if kind == TypeKind.STRING:
            return 'implicit'
        if kind in self._TRIVIAL_PRIMITIVE_KINDS:
            return 'free'
        if kind == TypeKind.ARRAY:
            return self.copy_tier(saw_type.array_element_type, _visiting)
        if kind == TypeKind.OPTIONAL:
            return self.copy_tier(saw_type.inner_type, _visiting)
        if kind == TypeKind.TUPLE:
            tier = 'free'
            for element in saw_type.element_types or []:
                tier = self._tier_join(tier, self.copy_tier(element, _visiting))
            return tier
        if kind == TypeKind.STRUCT:
            name = saw_type.struct_name
            if name is None:
                return 'free'
            alias_sym = self._lookup_type_alias_deep(name)
            if alias_sym and alias_sym.aliased_type:
                return self.copy_tier(alias_sym.aliased_type, _visiting)
            declared = self.declared_copy_tier(name)
            if declared != 'free':
                # A DECLARED policy is instantiation-uniform by construction:
                # `Vector<T>` is ExplicitCopy for every `T`. Nothing abstract
                # about the arguments can weaken or strengthen it.
                return declared
            if self.is_abstract_type_name(name):
                return 'abstract'
            if self._has_abstract_type_arg(saw_type):
                # An undeclared struct's 'free' is a STRUCTURAL answer, and a
                # structural answer over abstract arguments is not knowable from
                # the written type.
                return 'abstract'
            return 'free'
        if kind == TypeKind.ENUM:
            name = saw_type.enum_name
            if name is None:
                return 'free'
            declared = self.declared_copy_tier(name)
            if declared != 'free':
                return declared
            return self._enum_structural_copy_tier(saw_type, _visiting)
        return 'free'

    def _enum_structural_copy_tier(self, saw_type: SawType, _visiting=None) -> str:
        """The join of an enum's payload tiers, type arguments substituted in.

        This is what gives the compiler-owned wrappers their tier without a
        declaration to read: `Result`'s variants carry the opaque parameters
        `T`/`E`, so the payload types must be instantiated before they can be
        classified at all. A USER enum reaches here only when it declares no
        policy, which registration permits exactly when this join is 'free' or
        'implicit'.
        """
        name = saw_type.enum_name
        if _visiting is None:
            _visiting = frozenset()
        if name in _visiting:
            # An enum reaching itself through a payload. The back-edge adds no
            # tier of its own: whatever closes the cycle is behind a Box or an
            # Optional, each of which contributes its own tier at that field.
            return 'free'
        _visiting = _visiting | {name}
        sym = self._lookup_enum_deep(name)
        if sym is None:
            return 'free'
        type_map = self._enum_type_arg_map(sym, saw_type)
        tier = 'free'
        for variant_fields in sym.variants.values():
            for _fname, field_type in variant_fields:
                if field_type is None:
                    continue
                if type_map:
                    field_type = field_type.substitute(type_map)
                tier = self._tier_join(tier, self.copy_tier(field_type, _visiting))
        return tier

    def _enum_type_arg_map(self, sym, saw_type: SawType):
        """Map an enum's type-parameter names to an instantiation's arguments."""
        params = getattr(sym, 'type_params', None) or []
        args = saw_type.type_args or []
        if not params or not args:
            return {}
        return {p.name: a for p, a in zip(params, args) if a is not None}

    def is_implicit_copy_enum(self, saw_type: SawType, _visiting=None) -> bool:
        """Structural ImplicitCopy classification for enums (design 06 / DF12).

        Enums cannot DECLARE a Copy-family conformance (only Equatable/Comparable/
        Hashable opt-in), so their copy tier is derived from their payloads — the
        same containment precedence a struct's fields impose. This predicate is
        True iff the enum carries at least one OWNING (ImplicitCopy, e.g. `String`/
        `Arc`) payload AND every payload is cleanly retainable — trivially copyable
        (POD, bitwise) or itself ImplicitCopy. Such an enum copies by RETAINING its
        active payload (a refcount bump), exactly like an ImplicitCopy struct.

        A payload that is ExplicitCopy/NoCopy (e.g. `Vector`/`File`/`Box<any …>`)
        makes this False: that enum is move-only and is NOT implicitly copied — it
        keeps the pre-existing fall-through behavior (out of scope here). Without
        this, a `DepSource { PathDep(String) }`-style enum was silently BITWISE
        copied at every transfer while still releasing its payload at drop, so the
        shared `String` was released once per copy -> double free (DF12).

        The payload types are the enum's AS DECLARED, so a GENERIC enum must have
        its type arguments substituted in before they can be classified at all —
        `Slot<K>`'s payload is the opaque `K`, `Slot<Res>`'s is a real type with a
        real tier. Judging the unsubstituted form answered False for every generic
        enum, so a `Slot<Res>` value read emitted no copy while its binding was
        still dropped: one release per read, which is DF-146e.
        """
        saw_type = self._normalize_struct_enum(saw_type)
        if saw_type is None or saw_type.kind != TypeKind.ENUM:
            return False
        name = saw_type.enum_name
        if name is None:
            return False
        if _visiting is None:
            _visiting = set()
        if name in _visiting:
            # Recursion guard (an enum reaching itself through a payload): treat
            # the back-edge as retainable-but-non-owning so it neither loops nor
            # forces the whole enum non-retainable.
            return False
        _visiting = _visiting | {name}
        # A declared move-only conformance (defensive — enums can't declare these)
        # disqualifies implicit copying.
        if (self.type_conforms_to(name, "NoCopy")
                or self.type_conforms_to(name, "ExplicitCopy")):
            return False
        sym = self._lookup_enum_deep(name)
        if sym is None:
            return False
        type_map = self._enum_type_arg_map(sym, saw_type)
        has_owning = False
        for variant_fields in sym.variants.values():
            for _fname, ftype in variant_fields:
                if type_map and ftype is not None:
                    ftype = ftype.substitute(type_map)
                ok, owning = self._payload_retainable(ftype, _visiting)
                if not ok:
                    return False
                has_owning = has_owning or owning
        return has_owning

    def _payload_retainable(self, t: SawType, _visiting):
        """Classify an enum-payload field type for structural ImplicitCopy.

        Returns (retainable, owning): `retainable` is True when a copy of the enum
        can duplicate this field by a bitwise copy (POD) or a refcount retain
        (ImplicitCopy); `owning` is True only for a refcounted (ImplicitCopy) field
        — the presence of at least one is what makes the enclosing enum
        ImplicitCopy rather than trivially copyable.
        """
        if t is None:
            return (False, False)
        if self.is_trivially_copyable(t):
            return (True, False)
        k = t.kind
        if k == TypeKind.STRING:
            return (True, True)
        if k == TypeKind.OPTIONAL:
            return self._payload_retainable(t.inner_type, _visiting)
        if k == TypeKind.ARRAY:
            return self._payload_retainable(t.array_element_type, _visiting)
        if k == TypeKind.STRUCT:
            n = t.struct_name
            if n is not None and self.type_conforms_to(n, "ImplicitCopy"):
                return (True, True)
            # ExplicitCopy / NoCopy / Deinit struct: not cleanly retainable.
            return (False, False)
        if k == TypeKind.ENUM:
            if self.is_implicit_copy_enum(t, _visiting):
                return (True, True)
            # A payload-free / all-POD nested enum is bitwise-retainable (non-owning);
            # anything else (owning ExplicitCopy/NoCopy payload) is not.
            sym = self._lookup_enum_deep(t.enum_name) if t.enum_name else None
            if sym is not None:
                nested_map = self._enum_type_arg_map(sym, t)
                if all(self.is_trivially_copyable(
                            ft.substitute(nested_map) if nested_map and ft is not None
                            else ft)
                        for vf in sym.variants.values() for _n, ft in vf):
                    return (True, False)
            return (False, False)
        return (False, False)

    def _normalize_struct_enum(self, saw_type: SawType) -> SawType:
        """A type annotation like `-> Ordering` can reach the trait predicates as
        a STRUCT-kinded SawType (the parser defaults an unknown capitalized name
        to STRUCT, and not every path runs it through `_resolve_type`). If the
        name is actually a registered enum (and neither a struct nor an alias),
        rewrite it to an ENUM SawType so the enum branches fire."""
        if (saw_type is not None and saw_type.kind == TypeKind.STRUCT
                and saw_type.struct_name is not None
                and self._lookup_struct_deep(saw_type.struct_name) is None
                and self._lookup_type_alias_deep(saw_type.struct_name) is None
                and self._lookup_enum_deep(saw_type.struct_name) is not None):
            return SawType(TypeKind.ENUM, enum_name=saw_type.struct_name,
                           type_args=saw_type.type_args)
        return saw_type

    def is_equatable(self, saw_type: SawType) -> bool:
        saw_type = self._normalize_struct_enum(saw_type)
        """Whether values of `saw_type` may be compared with `==`/`!=` (design 32).

        Mirrors the Copy family's house rule:
          - primitives (integers, Bool, Float) and String conform builtin;
          - trivial (POD) structs and payload-free enums auto-conform (the exact
            auto-Copy set), so every field / payload is itself Equatable;
          - any struct or enum with a declared `extension T: Equatable {}` (or a
            hand-written `equals`) conforms;
          - tuples conform iff every element does (design 32 item 8).
        Resource types never satisfy this: they are neither trivially copyable
        nor accepted as Equatable conformers.
        """
        if saw_type is None:
            return False
        kind = saw_type.kind
        if kind in self._TRIVIAL_PRIMITIVE_KINDS:
            return True
        if kind == TypeKind.STRING:
            return True
        if kind == TypeKind.TUPLE:
            return all(self.is_equatable(e) for e in (saw_type.element_types or []))
        if kind == TypeKind.OPTIONAL:
            # Design 40 item 4 (L9): `T?` is Equatable iff `T` is — None==None
            # true, None vs Some false, payload-deep otherwise.
            return saw_type.inner_type is not None and self.is_equatable(saw_type.inner_type)
        if kind == TypeKind.ARRAY:
            # Design 40 item 4 (L9): `[T; N]` is Equatable iff its element type
            # is — compared element by element.
            return (saw_type.array_element_type is not None
                    and self.is_equatable(saw_type.array_element_type))
        if kind == TypeKind.STRUCT:
            name = saw_type.struct_name
            alias_sym = self._lookup_type_alias_deep(name)
            if alias_sym and alias_sym.aliased_type:
                return self.is_equatable(alias_sym.aliased_type)
            # Declared conformance (empty-body synthesis or a custom equals).
            if self.type_conforms_to(name, "Equatable"):
                return True
            # Auto-conform: the trivially-copyable (POD) set, exactly as
            # auto-Copy, further restricted to members the derive can actually
            # lower. is_trivially_copyable already excludes String / resource
            # fields; the field-wise is_equatable pass additionally excludes
            # optional / array members, which are not comparable yet.
            if not self.is_trivially_copyable(saw_type):
                return False
            struct_sym = self._lookup_struct_deep(name)
            if struct_sym is None:
                return False
            return all(self.is_equatable(ft) for ft in struct_sym.fields.values())
        if kind == TypeKind.ENUM:
            name = saw_type.enum_name
            if self.type_conforms_to(name, "Equatable"):
                return True
            # Auto-conform: payload-free enums keep their tag-only ==.
            enum_sym = self._lookup_enum_deep(name)
            if enum_sym is None:
                return False
            return all(len(fields) == 0 for fields in enum_sym.variants.values())
        return False

    _ORDERED_PRIMITIVE_KINDS = frozenset({
        TypeKind.INT, TypeKind.UINT,
        TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
        TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64,
        TypeKind.FLOAT,
    })

    def is_comparable(self, saw_type: SawType) -> bool:
        """Whether values of `saw_type` may be ordered with `< <= > >=` (design 48).

        Integer types, Float, and String conform builtin. There is NO auto-
        conformance for user types (field order is a semantic choice), so a
        struct/enum is Comparable only when it declares `extension T: Comparable`
        (empty-body synthesis or a hand-written `compare`). A type alias flows to
        its underlying type. Bool and other kinds are not ordered.
        """
        saw_type = self._normalize_struct_enum(saw_type)
        if saw_type is None:
            return False
        kind = saw_type.kind
        if kind in self._ORDERED_PRIMITIVE_KINDS:
            return True
        if kind == TypeKind.STRING:
            return True
        if kind == TypeKind.STRUCT:
            name = saw_type.struct_name
            alias_sym = self._lookup_type_alias_deep(name)
            if alias_sym and alias_sym.aliased_type:
                return self.is_comparable(alias_sym.aliased_type)
            return self.type_conforms_to(name, "Comparable")
        if kind == TypeKind.ENUM:
            return self.type_conforms_to(saw_type.enum_name, "Comparable")
        return False

    def is_hashable(self, saw_type: SawType) -> bool:
        """Whether values of `saw_type` may be used as a hash-map key (design 48).

        Mirrors `is_equatable`'s gating exactly (the hash/== contract rides on
        Equatable): primitives and String conform builtin; trivial (POD) structs
        and payload-free enums auto-conform; anything else opts in with
        `extension T: Hashable {}`; optionals/arrays/tuples are Hashable iff their
        elements are.
        """
        saw_type = self._normalize_struct_enum(saw_type)
        if saw_type is None:
            return False
        kind = saw_type.kind
        if kind in self._TRIVIAL_PRIMITIVE_KINDS:
            return True
        if kind == TypeKind.STRING:
            return True
        if kind == TypeKind.TUPLE:
            return all(self.is_hashable(e) for e in (saw_type.element_types or []))
        if kind == TypeKind.OPTIONAL:
            return saw_type.inner_type is not None and self.is_hashable(saw_type.inner_type)
        if kind == TypeKind.ARRAY:
            return (saw_type.array_element_type is not None
                    and self.is_hashable(saw_type.array_element_type))
        if kind == TypeKind.STRUCT:
            name = saw_type.struct_name
            alias_sym = self._lookup_type_alias_deep(name)
            if alias_sym and alias_sym.aliased_type:
                return self.is_hashable(alias_sym.aliased_type)
            if self.type_conforms_to(name, "Hashable"):
                return True
            if not self.is_trivially_copyable(saw_type):
                return False
            struct_sym = self._lookup_struct_deep(name)
            if struct_sym is None:
                return False
            return all(self.is_hashable(ft) for ft in struct_sym.fields.values())
        if kind == TypeKind.ENUM:
            name = saw_type.enum_name
            if self.type_conforms_to(name, "Hashable"):
                return True
            enum_sym = self._lookup_enum_deep(name)
            if enum_sym is None:
                return False
            return all(len(fields) == 0 for fields in enum_sym.variants.values())
        return False

    _PRINTABLE_PRIMITIVE_KINDS = frozenset({
        TypeKind.INT, TypeKind.UINT,
        TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
        TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64,
        TypeKind.FLOAT, TypeKind.BOOL,
    })

    def trait_refines(self, trait_name: str, target: str) -> bool:
        """Whether `trait_name` is `target` or transitively refines it via parent
        traits (e.g. `Error` refines `Printable`)."""
        seen = set()
        stack = [trait_name]
        while stack:
            name = stack.pop()
            if name == target:
                return True
            if name in seen:
                continue
            seen.add(name)
            info = self.lookup_trait(name)
            if info is None:
                for module_sym in self.modules.values():
                    if module_sym.namespace:
                        found = module_sym.namespace.lookup_trait(name)
                        if found is not None:
                            info = found
                            break
            if info is not None:
                stack.extend(getattr(info, 'parent_traits', []) or [])
        return False

    def _erased_trait_of(self, saw_type: SawType) -> Optional[str]:
        """The trait name if `saw_type` is an erased value (`any T`, `&any T`, or
        `Box<any T, A>`); else None (mirrors codegen's receiver detection)."""
        if saw_type is None:
            return None
        if saw_type.kind == TypeKind.EXISTENTIAL:
            return saw_type.existential_trait
        if (saw_type.kind == TypeKind.REFERENCE and saw_type.inner_type is not None
                and saw_type.inner_type.kind == TypeKind.EXISTENTIAL):
            return saw_type.inner_type.existential_trait
        if (saw_type.kind == TypeKind.STRUCT and saw_type.struct_name == "Box"
                and saw_type.type_args
                and saw_type.type_args[0].kind == TypeKind.EXISTENTIAL):
            return saw_type.type_args[0].existential_trait
        return None

    def is_printable(self, saw_type: SawType) -> bool:
        """Whether values of `saw_type` are Printable (design 56).

        Int/UInt + the fixed-width integer types, Float, Bool, and String conform
        BUILTIN (the compiler renders them inline). There is NO auto-conformance
        for user types — a struct/enum is Printable only when it declares
        `extension T: Printable` (or `extension T: Error`, which refines it) or a
        hand-written conformance. A type alias flows to its underlying type.
        """
        # An erased value (`any T` / `&any T` / `Box<any T, A>`) is Printable
        # when its trait is Printable or refines it (Error) — `to_string`/`format`
        # dispatch through the vtable (design 56, catch/erased-error interpolation).
        erased_trait = self._erased_trait_of(saw_type)
        if erased_trait is not None:
            return self.trait_refines(erased_trait, "Printable")
        saw_type = self._normalize_struct_enum(saw_type)
        if saw_type is None:
            return False
        kind = saw_type.kind
        if kind in self._PRINTABLE_PRIMITIVE_KINDS:
            return True
        if kind == TypeKind.STRING:
            return True
        if kind == TypeKind.STRUCT:
            name = saw_type.struct_name
            alias_sym = self._lookup_type_alias_deep(name)
            if alias_sym and alias_sym.aliased_type:
                return self.is_printable(alias_sym.aliased_type)
            return (self.type_conforms_to(name, "Printable")
                    or self.type_conforms_to(name, "Error"))
        if kind == TypeKind.ENUM:
            name = saw_type.enum_name
            return (self.type_conforms_to(name, "Printable")
                    or self.type_conforms_to(name, "Error"))
        return False

    def type_satisfies_bound(self, saw_type: SawType, bound: str) -> bool:
        """Whether a concrete type satisfies a single type-parameter bound.

        `Copy` is structural (trivially-copyable | ImplicitCopy | ExplicitCopy);
        `Send`/`Sync` are structural marker traits (design 21 item 1);
        `Equatable` is structural too (auto-Copy set + declared conformers,
        design 32); every other trait bound is an ordinary conformance lookup.
        """
        if bound == "Copy":
            return self.type_satisfies_copy_bound(saw_type)
        if bound == "Equatable":
            return self.is_equatable(saw_type)
        if bound == "Comparable":
            return self.is_comparable(saw_type)
        if bound == "Hashable":
            return self.is_hashable(saw_type)
        if bound == "Printable":
            return self.is_printable(saw_type)
        if bound == "Send":
            return self.is_send(saw_type)
        if bound == "Sync":
            return self.is_sync(saw_type)
        name = None
        if saw_type is None:
            return False
        if saw_type.kind == TypeKind.STRUCT:
            name = saw_type.struct_name
        elif saw_type.kind == TypeKind.ENUM:
            name = saw_type.enum_name
        elif saw_type.kind == TypeKind.STRING:
            name = "String"
        else:
            # A primitive that carries method extensions (design 57) conforms to
            # a user trait through the SAME conformance key the trait-method
            # dispatch uses for its pseudo-struct (`extension Int: Fooable`).
            # Only Int/Float register as extensible pseudo-structs; other
            # primitives cannot be extended, so their conformance set is empty.
            name = self._PRIMITIVE_CONFORMANCE_KEYS.get(saw_type.kind)
        if name is None:
            return False
        return self.type_conforms_to(name, bound)

    # =========================================================================
    # Send / Sync structural derivation (design 21 item 1)
    #
    # Compiler-known marker traits, auto-derived structurally (the auto-Copy
    # pattern). No explicit `extension X: Send` is accepted; these two methods
    # are the single source of truth for "is this concrete type Send / Sync",
    # shared by the typechecker's bound checks and the spawn capture audit.
    #
    #   - Primitives, Bool, Float: Send + Sync.
    #   - String: Send + Sync (immutable buffer, atomic refcount).
    #   - UnsafePointer<T>: neither (poisons its containers structurally).
    #   - Struct/enum: Send iff every field/payload is Send; Sync likewise.
    #   - Name-keyed overrides for the concurrency wrappers, whose raw-pointer
    #     fields would otherwise poison them structurally:
    #       Arc<T>:     Send + Sync  iff  T: Send + Sync
    #       Mutex<T>:   Send iff T: Send;   Sync iff T: Send
    #       Channel<T>: Send + Sync  iff  T: Send   (an Arc-like shared handle)
    #       Task<T>:    Send + Sync  iff  T: Send
    # =========================================================================

    def is_send(self, saw_type: SawType) -> bool:
        return self._send_sync(saw_type, want_sync=False, visiting=set())

    def is_sync(self, saw_type: SawType) -> bool:
        return self._send_sync(saw_type, want_sync=True, visiting=set())

    def _lookup_enum_deep(self, name: str) -> Optional[EnumSymbol]:
        result = self.lookup_enum(name)
        if result:
            return result
        for module_sym in self.modules.values():
            if module_sym.namespace:
                found = module_sym.namespace._lookup_enum_deep(name)
                if found:
                    return found
        return None

    def _send_sync(self, saw_type: SawType, want_sync: bool, visiting: set) -> bool:
        if saw_type is None:
            return False
        kind = saw_type.kind
        # Primitives / Bool / Float are trivially thread-safe.
        if kind in self._TRIVIAL_PRIMITIVE_KINDS or kind == TypeKind.VOID:
            return True
        # String: immutable buffer + atomic refcount (designed Send/Sync payoff).
        if kind == TypeKind.STRING:
            return True
        # UnsafePointer<T> is neither; it poisons any container structurally.
        if kind == TypeKind.POINTER:
            return False
        # References/closures are not user-nameable as Send/Sync bounds (v1);
        # closure-env Send-ness is audited at spawn sites, not here.
        if kind in (TypeKind.REFERENCE, TypeKind.FUNCTION):
            return False
        if kind == TypeKind.OPTIONAL:
            return self._send_sync(saw_type.inner_type, want_sync, visiting)
        if kind == TypeKind.TUPLE:
            return all(self._send_sync(e, want_sync, visiting)
                       for e in (saw_type.element_types or []))
        if kind == TypeKind.ARRAY:
            return self._send_sync(saw_type.array_element_type, want_sync, visiting)
        if kind == TypeKind.STRUCT:
            name = saw_type.struct_name
            args = saw_type.type_args or []
            # Type alias flows to its underlying type.
            alias_sym = self._lookup_type_alias_deep(name)
            if alias_sym and alias_sym.aliased_type:
                return self._send_sync(alias_sym.aliased_type, want_sync, visiting)
            # Concurrency-wrapper overrides (raw-pointer fields must not poison).
            if name == "Arc":
                inner = args[0] if args else None
                return (self._send_sync(inner, False, visiting) and
                        self._send_sync(inner, True, visiting))
            if name in ("Mutex", "Channel", "Task", "SpinLock"):
                inner = args[0] if args else None
                # Send iff T: Send; Sync iff T: Send (the wrappers add the sync).
                # `SpinLock` (design 149) is here for the same reason as `Mutex`:
                # it hands out `&var T` under mutual exclusion, so sharing one
                # across threads is safe exactly when MOVING a `T` across is.
                # Structurally it would also derive Sync from its `Atomic` word
                # and its payload, but that would make `SpinLock<T>` Sync for a
                # non-Send `T` — the wrapper is what adds the synchronization, so
                # the wrapper is what has to state the rule.
                return self._send_sync(inner, False, visiting)
            # design 46: UnsafeMemory<T, Use> is Send + Sync BY FIAT (the Atomic
            # precedent). It is one word (a fixed address); statics of this type
            # are shared across every task, so it must be Sync regardless of the
            # phantom `T` it views. Synchronization of the memory it names is the
            # programmer's responsibility (the Unsafe-prefix house rule).
            if name == "UnsafeMemory":
                return True
            # design 46: the layout-transparent field markers inherit their inner
            # type's thread-safety (they add no storage of their own).
            if name in ("ReadOnly", "WriteOnly"):
                inner = args[0] if args else None
                return self._send_sync(inner, want_sync, visiting)
            struct_sym = self._lookup_struct_deep(name)
            if struct_sym is None:
                # Opaque / unresolved type parameter: not structurally known.
                # (Abstract `T: Send` bodies are handled at the call site via
                # the parameter's declared bounds.)
                return False
            key = (name, tuple(str(a) for a in args))
            if key in visiting:
                return True  # co-recursive type: assume ok on the back-edge
            visiting = visiting | {key}
            subst = {}
            for tp, arg in zip(struct_sym.type_params, args):
                subst[tp.name] = arg
            for ft in struct_sym.fields.values():
                resolved = ft.substitute(subst) if subst else ft
                if not self._send_sync(resolved, want_sync, visiting):
                    return False
            return True
        if kind == TypeKind.ENUM:
            name = saw_type.enum_name
            args = saw_type.type_args or []
            enum_sym = self._lookup_enum_deep(name)
            if enum_sym is None:
                return False
            key = (name, tuple(str(a) for a in args))
            if key in visiting:
                return True
            visiting = visiting | {key}
            subst = {}
            for tp, arg in zip(enum_sym.type_params, args):
                subst[tp.name] = arg
            for payload in enum_sym.variants.values():
                for _field_name, ptype in payload:
                    resolved = ptype.substitute(subst) if subst else ptype
                    if not self._send_sync(resolved, want_sync, visiting):
                        return False
            return True
        # TYPE_PARAM / SELF / MODULE and anything else: not structurally known.
        return False

    def get_type_assignment(self, type_name: str, trait_name: str,
                           assoc_type_name: str) -> Optional[SawType]:
        """Get an associated type assignment."""
        if type_name not in self.conformances:
            return None
        trait_map = self.conformances[type_name].get(trait_name, {})
        return trait_map.get(assoc_type_name)

    def get_type_assignments(self, type_name: str, trait_name: str) -> Dict[str, SawType]:
        """Get all associated type assignments for a type/trait conformance.

        Args:
            type_name: The type implementing the trait
            trait_name: The trait being implemented

        Returns:
            Dict mapping associated type names to their concrete types
        """
        if type_name not in self.conformances:
            return {}
        return self.conformances[type_name].get(trait_name, {})

    def get_struct_fields(self, struct_name: str) -> Optional[Dict[str, SawType]]:
        """Get the fields of a struct."""
        struct = self.lookup_struct(struct_name)
        return struct.fields if struct else None

    def get_struct_field_order(self, struct_name: str) -> Optional[List[str]]:
        """Get the field order of a struct."""
        struct = self.lookup_struct(struct_name)
        return struct.field_order if struct else None

    def has_struct(self, name: str) -> bool:
        """Check if a struct exists."""
        return self.lookup_struct(name) is not None

    def has_enum(self, name: str) -> bool:
        """Check if an enum exists."""
        return self.lookup_enum(name) is not None

    def has_function(self, name: str) -> bool:
        """Check if a function exists."""
        return name in self.functions

    def has_trait(self, name: str) -> bool:
        """Check if a trait exists."""
        return self.lookup_trait(name) is not None

    # =========================================================================
    # Visibility Checking
    # =========================================================================

    def check_visibility(self, visibility: Visibility,
                        symbol_module: Tuple[str, ...],
                        accessor_module: Tuple[str, ...],
                        package_root: Tuple[str, ...] = ()) -> bool:
        """
        Check if a symbol is accessible from another module.

        Args:
            visibility: The symbol's visibility modifier
            symbol_module: Module path where the symbol is defined
            accessor_module: Module path that is trying to access the symbol
            package_root: The root of the current package (for public(package))

        Returns:
            True if access is allowed, False otherwise
        """
        # Public symbols are always accessible
        if visibility == Visibility.PUBLIC:
            return True

        # Private symbols are only accessible within the same module
        if visibility == Visibility.PRIVATE:
            return symbol_module == accessor_module

        # public(package) - accessible within the same package
        if visibility == Visibility.PACKAGE:
            # Check if both modules share the same package root
            if not package_root:
                # If no package root defined, assume same package
                return True
            # Both must be under the package root
            return (symbol_module[:len(package_root)] == package_root and
                    accessor_module[:len(package_root)] == package_root)

        # public(parent) - accessible to parent module only
        if visibility == Visibility.PARENT:
            # accessor_module must be the parent of symbol_module
            if len(symbol_module) < 1:
                return False
            parent = symbol_module[:-1]
            return accessor_module == parent

        return False

    def get_symbol_visibility(self, name: str) -> Optional[Visibility]:
        """Get the visibility of a symbol by name."""
        for _lookup in (self.lookup_struct, self.lookup_enum):
            sym = _lookup(name)
            if sym is not None:
                return sym.visibility
        if name in self.functions:
            return self.functions[name].visibility
        for _lookup in (self.lookup_trait, self.lookup_type_alias):
            sym = _lookup(name)
            if sym is not None:
                return sym.visibility
        return None

    # =========================================================================
    # Generic Instantiation Tracking
    # =========================================================================

    def mark_instantiated(self, mangled_name: str):
        """Mark a generic instantiation as generated."""
        self.instantiated.add(mangled_name)

    def is_instantiated(self, mangled_name: str) -> bool:
        """Check if a generic instantiation has been generated."""
        return mangled_name in self.instantiated

    # =========================================================================
    # Namespace Merging
    # =========================================================================

    def merge_into(self, other: 'Namespace', source_label: Optional[str] = None,
                   collisions: Optional[List[Tuple[str, str, str, str]]] = None,
                   exclude: Optional[set] = None):
        """
        Merge another namespace's symbols into this one.

        Used for codegen when combining per-module namespaces into a unified
        namespace. Existing symbols in this namespace are NOT overwritten.

        Collision policy (design 26 item 1): merging is a size-1-first-wins
        operation, but a first-wins that silently drops a *different* symbol
        object under an already-taken name is a genuine ambiguity — two modules
        each defining `foo`. We surface those honestly. Builtins are shared by
        reference across every module namespace (each module clones them via
        `merge_into`), so re-merging the same object is benign and never flagged;
        only a name bound to a *distinct* object counts as a collision.

        Args:
            source_label: A human-readable label for `other` (e.g. a module path
                string). When provided, each first-seen symbol records this label
                as its provenance so a later collision can name both sides.
            collisions: Optional accumulator; when provided, each detected
                collision appends a ``(category, name, existing_label, new_label)``
                tuple. Collisions are checked for the value symbol categories
                (structs, enums, functions, traits, type aliases), not for
                module aliases or generic AST storage.
        """
        def _module_local(sym) -> bool:
            """Whether `sym` is a module-PRIVATE declaration carrying a
            module-local codegen symbol (DF-140f). Such a declaration cannot be
            named from another module — no importer could be ambiguous about it
            — and its definition no longer shares an LLVM name with a same-named
            private declaration elsewhere, so a name it happens to share is not
            a collision at all."""
            return (getattr(sym, 'visibility', None) == Visibility.PRIVATE
                    and bool(getattr(sym, 'mangled_name', "")))

        def _merge(category: str, dst: Dict[str, Any], src: Dict[str, Any],
                   private_is_local: bool = False):
            for name, sym in src.items():
                # design 82 Part B: a std symbol whose module is not compiled into
                # this program (non-imported import-required std) is skipped, so a
                # user type of the same name does not collide with it.
                if exclude and name in exclude:
                    continue
                existing = dst.get(name)
                if existing is None:
                    dst[name] = sym
                    if source_label is not None:
                        self._provenance[name] = source_label
                elif existing is not sym and collisions is not None:
                    if private_is_local and (_module_local(sym)
                                             or _module_local(existing)):
                        continue
                    prev = self._provenance.get(name, "<unknown>")
                    collisions.append((category, name, prev,
                                       source_label if source_label is not None
                                       else "<unknown>"))

        # Design 144: these four tables are keyed by module-qualified type
        # IDENTITY, so two modules' `Header`s land on two keys and never meet
        # here. What remains a genuine collision is one identity bound to two
        # distinct symbols — the same module declaring a name twice — which is
        # still worth reporting. The AMBIGUITY a bare `Header` faces when two
        # modules export one is not a merge event at all; it is the use-site
        # error, carried by `type_names`/`ambiguous_types` below.
        _merge("struct", self.structs, other.structs)
        _merge("enum", self.enums, other.enums)
        _merge("function", self.functions, other.functions,
               private_is_local=True)
        # Overloading (design 55): carry each name's full overload set across the
        # merge (first-wins per name, matching the representative merge above).
        for _name, _lst in other.function_overloads.items():
            if _name not in self.function_overloads:
                self.function_overloads[_name] = list(_lst)
        _merge("trait", self.traits, other.traits)
        _merge("type alias", self.type_aliases, other.type_aliases)
        # Statics (design 41): same identity/collision rule (design 26) as the
        # other value symbols — two modules each defining a distinct PUBLIC
        # static of the same name is an unresolvable ambiguity, surfaced here.
        # A module-private one is not (DF-140f): it is unnameable from outside
        # and carries a module-local LLVM global, so the two never meet.
        _merge("static", self.statics, other.statics, private_is_local=True)
        # DF-140h: the per-module overlays travel too, keyed by defining module,
        # so a std file's private constants stay reachable from that file's own
        # bodies after the merge and from nowhere else. Two modules' overlays can
        # never collide — the module path is part of the key.
        for _mod, _tbl in other.module_statics.items():
            _dst = self.module_statics.setdefault(_mod, {})
            for _n, _s in _tbl.items():
                _dst.setdefault(_n, _s)
        # Design 144: the source-name -> identity view travels too, so the
        # merged namespace can still answer a bare-name query (codegen asks by
        # identity, but the place lowering and the re-entered front half ask by
        # name). Two modules binding one name to two identities marks the name
        # ambiguous rather than silently picking the first.
        for _n, _ident in other.type_names.items():
            self.bind_type_name(_n, _ident, "type", source_label)
        for _n, _amb in other.ambiguous_types.items():
            self.ambiguous_types.setdefault(_n, _amb)
        for name, sym in other.modules.items():
            if name not in self.modules:
                self.modules[name] = sym
        # Merge conformances
        for type_name, iface_map in other.conformances.items():
            if type_name not in self.conformances:
                self.conformances[type_name] = {}
            for iface_name, assoc_types in iface_map.items():
                if iface_name not in self.conformances[type_name]:
                    self.conformances[type_name][iface_name] = assoc_types
        # Merge generic AST storage
        for name, ast in other.generic_functions.items():
            if name not in self.generic_functions:
                self.generic_functions[name] = ast
        for name, ast in other.generic_structs.items():
            if name not in self.generic_structs:
                self.generic_structs[name] = ast
        for name, ast in other.generic_enums.items():
            if name not in self.generic_enums:
                self.generic_enums[name] = ast
        for name, exts in other.generic_extensions.items():
            if name not in self.generic_extensions:
                self.generic_extensions[name] = exts
            else:
                # Extend the list of extensions
                self.generic_extensions[name].extend(exts)

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
    visibility: Visibility = Visibility.PRIVATE
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
    line: int = 0
    column: int = 0
    ast_node: Optional[Struct] = None
    # Specialized methods for specific type arguments (e.g., extension Vector<String>)
    # Key: tuple of type arg strings like ("String",), Value: method_name -> FunctionSymbol
    specialized_methods: Dict[Tuple[str, ...], Dict[str, FunctionSymbol]] = field(default_factory=dict)


@dataclass
class EnumSymbol:
    """Symbol for an enum type."""
    kind: SymbolKind = SymbolKind.ENUM
    variants: Dict[str, List[Tuple[str, SawType]]] = field(default_factory=dict)
    variant_order: List[str] = field(default_factory=list)
    type_params: List[TypeParameter] = field(default_factory=list)
    visibility: Visibility = Visibility.PRIVATE
    ast_node: Optional[SawEnum] = None


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


@dataclass
class TypeAliasSymbol:
    """Symbol for a type alias."""
    kind: SymbolKind = SymbolKind.TYPE_ALIAS
    aliased_type: Optional[SawType] = None
    visibility: Visibility = Visibility.PRIVATE


@dataclass
class StaticSymbol:
    """Symbol for a module-level `static` declaration (design 41).

    Statics are Sync-only, const-initialized, immortal, and immutable (no
    `static mut`). `mangled_name` is the codegen identity — the LLVM global's
    name, prefixed so it never clashes with a function of the same name in the
    (shared) LLVM value symbol table.
    """
    kind: SymbolKind = SymbolKind.STATIC
    type: Optional[SawType] = None
    mangled_name: str = ""
    visibility: Visibility = Visibility.PRIVATE
    line: int = 0
    column: int = 0


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
        self.structs: Dict[str, StructSymbol] = {}
        self.enums: Dict[str, EnumSymbol] = {}
        self.traits: Dict[str, TraitSymbol] = {}
        self.type_aliases: Dict[str, TypeAliasSymbol] = {}
        self.modules: Dict[str, ModuleSymbol] = {}
        # Module-level `static` declarations (design 41), keyed by simple name.
        self.statics: Dict[str, StaticSymbol] = {}

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

        if name in self.structs:
            sym = self.structs[name]
            return sym if is_visible(sym) else None
        if name in self.enums:
            sym = self.enums[name]
            return sym if is_visible(sym) else None
        if name in self.traits:
            sym = self.traits[name]
            return sym if is_visible(sym) else None
        if name in self.type_aliases:
            sym = self.type_aliases[name]
            return sym if is_visible(sym) else None
        if name in self.functions:
            sym = self.functions[name]
            return sym if is_visible(sym) else None
        if name in self.statics:
            sym = self.statics[name]
            return sym if is_visible(sym) else None

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

    def register_static(self, name: str, symbol: 'StaticSymbol'):
        """Register a module-level static symbol (design 41)."""
        self.statics[name] = symbol

    def has_static(self, name: str) -> bool:
        """Check if a static exists."""
        return name in self.statics

    def get_static(self, name: str) -> Optional['StaticSymbol']:
        """Look up a static symbol by simple name."""
        return self.statics.get(name)

    def register_struct(self, name: str, symbol: StructSymbol):
        """Register a struct symbol."""
        self.structs[name] = symbol

    def register_enum(self, name: str, symbol: EnumSymbol):
        """Register an enum symbol."""
        self.enums[name] = symbol

    def register_trait(self, name: str, symbol: TraitSymbol):
        """Register a trait symbol."""
        self.traits[name] = symbol

    def register_type_alias(self, name: str, symbol: TypeAliasSymbol):
        """Register a type alias symbol."""
        self.type_aliases[name] = symbol

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

    def register_method(self, struct_name: str, method_name: str, symbol: FunctionSymbol):
        """Register a method on a struct (design 55: appends to the overload set).

        The first registration under a name is the representative in `methods`;
        later overloads only extend `method_overloads`.
        """
        if struct_name in self.structs:
            s = self.structs[struct_name]
            s.method_overloads.setdefault(method_name, []).append(symbol)
            if method_name not in s.methods:
                s.methods[method_name] = symbol

    def lookup_method_overloads(self, struct_name: str, method_name: str) -> List[FunctionSymbol]:
        """All overloads of `method_name` on `struct_name` (design 55)."""
        struct = self.structs.get(struct_name)
        if struct:
            return struct.method_overloads.get(method_name, [])
        return []

    def register_init_method(self, struct_name: str, symbol: FunctionSymbol):
        """Register an init method on a struct."""
        if struct_name in self.structs:
            self.structs[struct_name].init_methods.append(symbol)

    def register_specialized_method(self, struct_name: str, spec_key: Tuple[str, ...],
                                     method_name: str, method: FunctionSymbol):
        """Register a specialized method for a generic struct instantiation.

        Args:
            struct_name: The base struct name (e.g., "Vector")
            spec_key: Tuple of type argument strings (e.g., ("String",))
            method_name: The method name
            method: The FunctionSymbol for the method
        """
        struct_sym = self.structs.get(struct_name)
        if struct_sym:
            if spec_key not in struct_sym.specialized_methods:
                struct_sym.specialized_methods[spec_key] = {}
            struct_sym.specialized_methods[spec_key][method_name] = method

    def register_conformance(self, type_name: str, trait_name: str,
                            type_assignments: Optional[Dict[str, SawType]] = None):
        """Register that a type conforms to a trait."""
        if type_name not in self.conformances:
            self.conformances[type_name] = {}
        self.conformances[type_name][trait_name] = type_assignments or {}

        # Also add to struct's conformance list
        if type_name in self.structs:
            if trait_name not in self.structs[type_name].conformances:
                self.structs[type_name].conformances.append(trait_name)

    # =========================================================================
    # Lookup Methods
    # =========================================================================

    def lookup_function(self, name: str) -> Optional[FunctionSymbol]:
        """Look up a function by name."""
        return self.functions.get(name)

    def lookup_struct(self, name: str) -> Optional[StructSymbol]:
        """Look up a struct by name."""
        return self.structs.get(name)

    def lookup_enum(self, name: str) -> Optional[EnumSymbol]:
        """Look up an enum by name."""
        return self.enums.get(name)

    def lookup_trait(self, name: str) -> Optional[TraitSymbol]:
        """Look up a trait by name."""
        return self.traits.get(name)

    def lookup_type_alias(self, name: str) -> Optional[TypeAliasSymbol]:
        """Look up a type alias by name."""
        return self.type_aliases.get(name)

    def lookup_method(self, struct_name: str, method_name: str) -> Optional[FunctionSymbol]:
        """Look up a method on a struct."""
        struct = self.structs.get(struct_name)
        if struct:
            return struct.methods.get(method_name)
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
        struct = self.structs.get(struct_name)
        if struct and spec_key in struct.specialized_methods:
            return struct.specialized_methods[spec_key].get(method_name)
        return None

    def lookup_type(self, name: str) -> Optional[SawType]:
        """Resolve a type name to its SawType."""
        # Check type aliases first
        if name in self.type_aliases and self.type_aliases[name].aliased_type:
            return self.type_aliases[name].aliased_type
        # Check structs
        if name in self.structs:
            return SawType(kind=TypeKind.STRUCT, struct_name=name)
        # Check enums
        if name in self.enums:
            return SawType(kind=TypeKind.ENUM, enum_name=name)
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

    def type_conforms_to(self, type_name: str, trait_name: str) -> bool:
        """Check if a type conforms to a trait."""
        if type_name not in self.conformances:
            return False
        return trait_name in self.conformances[type_name]

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

    def _lookup_struct_deep(self, name: str) -> Optional[StructSymbol]:
        """Look up a struct in this namespace or any imported module namespace."""
        result = self.structs.get(name)
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
        result = self.type_aliases.get(name)
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
        return False

    def type_satisfies_copy_bound(self, saw_type: SawType) -> bool:
        """Whether a concrete type satisfies the umbrella `Copy` bound:
        trivially copyable, or declaring ImplicitCopy / ExplicitCopy (or Copy)."""
        if saw_type is None:
            return False
        if self.is_trivially_copyable(saw_type):
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

    def is_printable(self, saw_type: SawType) -> bool:
        """Whether values of `saw_type` are Printable (design 56).

        Int/UInt + the fixed-width integer types, Float, Bool, and String conform
        BUILTIN (the compiler renders them inline). There is NO auto-conformance
        for user types — a struct/enum is Printable only when it declares
        `extension T: Printable` (or `extension T: Error`, which refines it) or a
        hand-written conformance. A type alias flows to its underlying type.
        """
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
        result = self.enums.get(name)
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
            if name in ("Mutex", "Channel", "Task"):
                inner = args[0] if args else None
                # Send iff T: Send; Sync iff T: Send (the wrappers add the sync).
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
        struct = self.structs.get(struct_name)
        return struct.fields if struct else None

    def get_struct_field_order(self, struct_name: str) -> Optional[List[str]]:
        """Get the field order of a struct."""
        struct = self.structs.get(struct_name)
        return struct.field_order if struct else None

    def has_struct(self, name: str) -> bool:
        """Check if a struct exists."""
        return name in self.structs

    def has_enum(self, name: str) -> bool:
        """Check if an enum exists."""
        return name in self.enums

    def has_function(self, name: str) -> bool:
        """Check if a function exists."""
        return name in self.functions

    def has_trait(self, name: str) -> bool:
        """Check if a trait exists."""
        return name in self.traits

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
        if name in self.structs:
            return self.structs[name].visibility
        if name in self.enums:
            return self.enums[name].visibility
        if name in self.functions:
            return self.functions[name].visibility
        if name in self.traits:
            return self.traits[name].visibility
        if name in self.type_aliases:
            return self.type_aliases[name].visibility
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
                   collisions: Optional[List[Tuple[str, str, str, str]]] = None):
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
        def _merge(category: str, dst: Dict[str, Any], src: Dict[str, Any]):
            for name, sym in src.items():
                existing = dst.get(name)
                if existing is None:
                    dst[name] = sym
                    if source_label is not None:
                        self._provenance[name] = source_label
                elif existing is not sym and collisions is not None:
                    prev = self._provenance.get(name, "<unknown>")
                    collisions.append((category, name, prev,
                                       source_label if source_label is not None
                                       else "<unknown>"))

        _merge("struct", self.structs, other.structs)
        _merge("enum", self.enums, other.enums)
        _merge("function", self.functions, other.functions)
        # Overloading (design 55): carry each name's full overload set across the
        # merge (first-wins per name, matching the representative merge above).
        for _name, _lst in other.function_overloads.items():
            if _name not in self.function_overloads:
                self.function_overloads[_name] = list(_lst)
        _merge("trait", self.traits, other.traits)
        _merge("type alias", self.type_aliases, other.type_aliases)
        # Statics (design 41): same identity/collision rule (design 26) as the
        # other value symbols — two modules each defining a distinct static of
        # the same name is an unresolvable ambiguity, surfaced here.
        _merge("static", self.statics, other.statics)
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

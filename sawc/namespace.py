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
    INTERFACE = auto()
    TYPE_ALIAS = auto()
    MODULE = auto()


@dataclass
class FunctionSymbol:
    """Symbol for a function or method."""
    kind: SymbolKind = SymbolKind.FUNCTION
    param_types: List[SawType] = field(default_factory=list)
    param_names: List[str] = field(default_factory=list)
    return_type: Optional[SawType] = None
    type_params: List[TypeParameter] = field(default_factory=list)
    defaults: List[Optional[Any]] = field(default_factory=list)
    is_static: bool = False
    is_init: bool = False
    self_mutable: bool = False
    is_variadic: bool = False
    visibility: Visibility = Visibility.PRIVATE
    ast_node: Optional[Any] = None  # Function or Method AST node
    # Filled by codegen:
    llvm_func: Optional[Any] = None


@dataclass
class StructSymbol:
    """Symbol for a struct type."""
    kind: SymbolKind = SymbolKind.STRUCT
    fields: Dict[str, SawType] = field(default_factory=dict)
    field_order: List[str] = field(default_factory=list)
    type_params: List[TypeParameter] = field(default_factory=list)
    methods: Dict[str, FunctionSymbol] = field(default_factory=dict)
    init_methods: List[FunctionSymbol] = field(default_factory=list)
    conformances: List[str] = field(default_factory=list)
    visibility: Visibility = Visibility.PRIVATE
    line: int = 0
    column: int = 0
    ast_node: Optional[Struct] = None
    # Filled by codegen:
    llvm_type: Optional[Any] = None


@dataclass
class EnumSymbol:
    """Symbol for an enum type."""
    kind: SymbolKind = SymbolKind.ENUM
    variants: Dict[str, List[Tuple[str, SawType]]] = field(default_factory=dict)
    variant_order: List[str] = field(default_factory=list)
    type_params: List[TypeParameter] = field(default_factory=list)
    visibility: Visibility = Visibility.PRIVATE
    ast_node: Optional[SawEnum] = None
    # Filled by codegen:
    llvm_type: Optional[Any] = None
    variant_tags: Optional[Dict[str, int]] = None


@dataclass
class InterfaceMethodSymbol:
    """Symbol for a method signature in an interface."""
    name: str
    param_types: List[SawType] = field(default_factory=list)
    param_names: List[str] = field(default_factory=list)
    return_type: Optional[SawType] = None
    self_mutable: bool = False


@dataclass
class InterfaceSymbol:
    """Symbol for an interface."""
    kind: SymbolKind = SymbolKind.INTERFACE
    methods: Dict[str, InterfaceMethodSymbol] = field(default_factory=dict)
    associated_types: List[str] = field(default_factory=list)
    parent_interfaces: List[str] = field(default_factory=list)
    visibility: Visibility = Visibility.PRIVATE


@dataclass
class TypeAliasSymbol:
    """Symbol for a type alias."""
    kind: SymbolKind = SymbolKind.TYPE_ALIAS
    aliased_type: Optional[SawType] = None
    visibility: Visibility = Visibility.PRIVATE


@dataclass
class ModuleSymbol:
    """Symbol for an imported module."""
    kind: SymbolKind = SymbolKind.MODULE
    # The module's own namespace containing its symbols
    namespace: Optional['Namespace'] = None
    # Original module path (e.g., ["std", "io"])
    path: List[str] = field(default_factory=list)


# Union type for any symbol that can be resolved
Symbol = Union[FunctionSymbol, StructSymbol, EnumSymbol, InterfaceSymbol, TypeAliasSymbol, ModuleSymbol]


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
        self.structs: Dict[str, StructSymbol] = {}
        self.enums: Dict[str, EnumSymbol] = {}
        self.interfaces: Dict[str, InterfaceSymbol] = {}
        self.type_aliases: Dict[str, TypeAliasSymbol] = {}
        self.modules: Dict[str, ModuleSymbol] = {}

        # Type conformances: type_name -> {interface_name -> {assoc_type_name -> SawType}}
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

        # Check all symbol tables
        # Order: modules first (for qualified access), then types, then functions
        if name in self.modules:
            return self.modules[name]

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

        if name in self.structs:
            sym = self.structs[name]
            return sym if is_visible(sym) else None
        if name in self.enums:
            sym = self.enums[name]
            return sym if is_visible(sym) else None
        if name in self.interfaces:
            sym = self.interfaces[name]
            return sym if is_visible(sym) else None
        if name in self.type_aliases:
            sym = self.type_aliases[name]
            return sym if is_visible(sym) else None
        if name in self.functions:
            sym = self.functions[name]
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
        """Register a function symbol."""
        self.functions[name] = symbol

    def register_struct(self, name: str, symbol: StructSymbol):
        """Register a struct symbol."""
        self.structs[name] = symbol

    def register_enum(self, name: str, symbol: EnumSymbol):
        """Register an enum symbol."""
        self.enums[name] = symbol

    def register_interface(self, name: str, symbol: InterfaceSymbol):
        """Register an interface symbol."""
        self.interfaces[name] = symbol

    def register_type_alias(self, name: str, symbol: TypeAliasSymbol):
        """Register a type alias symbol."""
        self.type_aliases[name] = symbol

    def register_module(self, alias: str, symbol: ModuleSymbol):
        """Register a module symbol (for imports)."""
        self.modules[alias] = symbol

    def register_module_from_ast(self, alias: str, module_ast: 'Program', path: List[str] = None):
        """
        Create and register a module from a parsed AST.

        This builds a namespace from the module's declarations and registers
        it under the given alias.

        Args:
            alias: The local name for the module (e.g., "utils")
            module_ast: The parsed Program AST for the module
            path: The original module path (e.g., ["modules", "utils"])
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

        for iface in module_ast.interfaces:
            methods = {}
            assoc_types = []
            for m in iface.methods:
                methods[m.name] = InterfaceMethodSymbol(
                    name=m.name,
                    param_types=[p.type for p in m.parameters],
                    param_names=[p.name for p in m.parameters],
                    return_type=m.return_type,
                    self_mutable=m.self_mutable
                )
            for at in iface.associated_types:
                assoc_types.append(at.name)
            mod_ns.register_interface(iface.name, InterfaceSymbol(
                methods=methods,
                associated_types=assoc_types,
                visibility=iface.visibility
            ))

        # Create and register the module symbol
        self.modules[alias] = ModuleSymbol(
            namespace=mod_ns,
            path=path or []
        )

    def register_method(self, struct_name: str, method_name: str, symbol: FunctionSymbol):
        """Register a method on a struct."""
        if struct_name in self.structs:
            self.structs[struct_name].methods[method_name] = symbol

    def register_init_method(self, struct_name: str, symbol: FunctionSymbol):
        """Register an init method on a struct."""
        if struct_name in self.structs:
            self.structs[struct_name].init_methods.append(symbol)

    def register_conformance(self, type_name: str, interface_name: str,
                            type_assignments: Optional[Dict[str, SawType]] = None):
        """Register that a type conforms to an interface."""
        if type_name not in self.conformances:
            self.conformances[type_name] = {}
        self.conformances[type_name][interface_name] = type_assignments or {}

        # Also add to struct's conformance list
        if type_name in self.structs:
            if interface_name not in self.structs[type_name].conformances:
                self.structs[type_name].conformances.append(interface_name)

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

    def lookup_interface(self, name: str) -> Optional[InterfaceSymbol]:
        """Look up an interface by name."""
        return self.interfaces.get(name)

    def lookup_type_alias(self, name: str) -> Optional[TypeAliasSymbol]:
        """Look up a type alias by name."""
        return self.type_aliases.get(name)

    def lookup_method(self, struct_name: str, method_name: str) -> Optional[FunctionSymbol]:
        """Look up a method on a struct."""
        struct = self.structs.get(struct_name)
        if struct:
            return struct.methods.get(method_name)
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

    def type_conforms_to(self, type_name: str, interface_name: str) -> bool:
        """Check if a type conforms to an interface."""
        if type_name not in self.conformances:
            return False
        return interface_name in self.conformances[type_name]

    def get_conformances(self, type_name: str) -> List[str]:
        """Get all interfaces a type conforms to."""
        if type_name not in self.conformances:
            return []
        return list(self.conformances[type_name].keys())

    def get_type_assignment(self, type_name: str, interface_name: str,
                           assoc_type_name: str) -> Optional[SawType]:
        """Get an associated type assignment."""
        if type_name not in self.conformances:
            return None
        iface_map = self.conformances[type_name].get(interface_name, {})
        return iface_map.get(assoc_type_name)

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

    def has_interface(self, name: str) -> bool:
        """Check if an interface exists."""
        return name in self.interfaces

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
        if name in self.interfaces:
            return self.interfaces[name].visibility
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


# =============================================================================
# Module-Qualified Namespace
# =============================================================================

@dataclass
class ImportedSymbol:
    """Tracks an imported symbol in a module's scope."""
    kind: SymbolKind          # What kind of symbol this is
    source_path: Tuple[str, ...]  # Module path where symbol is defined
    name: str                 # Original symbol name
    alias: Optional[str] = None  # Local alias (if any)

    @property
    def local_name(self) -> str:
        """The name this symbol is accessed by locally."""
        return self.alias or self.name


class ModuleNamespace:
    """
    Module-aware namespace that supports multi-file compilation.

    This extends the basic Namespace with:
    - Module path tracking for each symbol
    - Import resolution for cross-module references
    - Qualified symbol lookup (e.g., io.File)
    """

    def __init__(self):
        # Module path -> Namespace (each module has its own namespace)
        self.modules: Dict[Tuple[str, ...], Namespace] = {}

        # Root namespace for non-module (legacy) compilation
        self.root = Namespace()

        # Current module context during type checking
        self.current_module: Tuple[str, ...] = ()

        # Module path -> list of imported symbols
        self.imports: Dict[Tuple[str, ...], List[ImportedSymbol]] = {}

        # Module path -> set of glob-imported module paths
        self.glob_imports: Dict[Tuple[str, ...], List[Tuple[str, ...]]] = {}

        # Module path -> alias -> actual module path (for `import foo as bar`)
        self.module_aliases: Dict[Tuple[str, ...], Dict[str, Tuple[str, ...]]] = {}

    def get_or_create_module(self, path: Tuple[str, ...]) -> Namespace:
        """Get or create a namespace for a module path."""
        if path not in self.modules:
            self.modules[path] = Namespace()
        return self.modules[path]

    def register_import(self, in_module: Tuple[str, ...],
                       from_module: Tuple[str, ...],
                       symbol_name: str,
                       symbol_kind: SymbolKind,
                       alias: Optional[str] = None):
        """Register an imported symbol in a module's scope."""
        if in_module not in self.imports:
            self.imports[in_module] = []

        self.imports[in_module].append(ImportedSymbol(
            kind=symbol_kind,
            source_path=from_module,
            name=symbol_name,
            alias=alias
        ))

    def register_module_import(self, in_module: Tuple[str, ...],
                              imported_module: Tuple[str, ...],
                              alias: Optional[str] = None):
        """Register a module import (import std.io or import std.io as io)."""
        if in_module not in self.module_aliases:
            self.module_aliases[in_module] = {}

        # The module is accessible as its last component or the alias
        local_name = alias or imported_module[-1] if imported_module else ""
        self.module_aliases[in_module][local_name] = imported_module

    def register_glob_import(self, in_module: Tuple[str, ...],
                            from_module: Tuple[str, ...]):
        """Register a glob import (import foo.*)."""
        if in_module not in self.glob_imports:
            self.glob_imports[in_module] = []
        self.glob_imports[in_module].append(from_module)

    def lookup_struct(self, name: str, in_module: Optional[Tuple[str, ...]] = None) -> Optional[StructSymbol]:
        """
        Look up a struct, checking:
        1. Current module's own declarations
        2. Explicitly imported symbols
        3. Glob-imported modules
        4. Root namespace (for builtins)
        """
        module_path = in_module or self.current_module

        # Check current module's namespace
        if module_path in self.modules:
            result = self.modules[module_path].lookup_struct(name)
            if result:
                return result

        # Check explicit imports
        if module_path in self.imports:
            for imp in self.imports[module_path]:
                if imp.local_name == name and imp.kind == SymbolKind.STRUCT:
                    # Look up in the source module
                    if imp.source_path in self.modules:
                        return self.modules[imp.source_path].lookup_struct(imp.name)

        # Check glob imports
        if module_path in self.glob_imports:
            for glob_module in self.glob_imports[module_path]:
                if glob_module in self.modules:
                    result = self.modules[glob_module].lookup_struct(name)
                    if result:
                        return result

        # Fall back to root namespace (builtins)
        return self.root.lookup_struct(name)

    def lookup_enum(self, name: str, in_module: Optional[Tuple[str, ...]] = None) -> Optional[EnumSymbol]:
        """Look up an enum with module-aware resolution."""
        module_path = in_module or self.current_module

        if module_path in self.modules:
            result = self.modules[module_path].lookup_enum(name)
            if result:
                return result

        if module_path in self.imports:
            for imp in self.imports[module_path]:
                if imp.local_name == name and imp.kind == SymbolKind.ENUM:
                    if imp.source_path in self.modules:
                        return self.modules[imp.source_path].lookup_enum(imp.name)

        if module_path in self.glob_imports:
            for glob_module in self.glob_imports[module_path]:
                if glob_module in self.modules:
                    result = self.modules[glob_module].lookup_enum(name)
                    if result:
                        return result

        return self.root.lookup_enum(name)

    def lookup_function(self, name: str, in_module: Optional[Tuple[str, ...]] = None) -> Optional[FunctionSymbol]:
        """Look up a function with module-aware resolution."""
        module_path = in_module or self.current_module

        if module_path in self.modules:
            result = self.modules[module_path].lookup_function(name)
            if result:
                return result

        if module_path in self.imports:
            for imp in self.imports[module_path]:
                if imp.local_name == name and imp.kind == SymbolKind.FUNCTION:
                    if imp.source_path in self.modules:
                        return self.modules[imp.source_path].lookup_function(imp.name)

        if module_path in self.glob_imports:
            for glob_module in self.glob_imports[module_path]:
                if glob_module in self.modules:
                    result = self.modules[glob_module].lookup_function(name)
                    if result:
                        return result

        return self.root.lookup_function(name)

    def lookup_interface(self, name: str, in_module: Optional[Tuple[str, ...]] = None) -> Optional[InterfaceSymbol]:
        """Look up an interface with module-aware resolution."""
        module_path = in_module or self.current_module

        if module_path in self.modules:
            result = self.modules[module_path].lookup_interface(name)
            if result:
                return result

        if module_path in self.imports:
            for imp in self.imports[module_path]:
                if imp.local_name == name and imp.kind == SymbolKind.INTERFACE:
                    if imp.source_path in self.modules:
                        return self.modules[imp.source_path].lookup_interface(imp.name)

        if module_path in self.glob_imports:
            for glob_module in self.glob_imports[module_path]:
                if glob_module in self.modules:
                    result = self.modules[glob_module].lookup_interface(name)
                    if result:
                        return result

        return self.root.lookup_interface(name)

    def lookup_qualified(self, qualifier: str, name: str,
                        in_module: Optional[Tuple[str, ...]] = None,
                        check_visibility: bool = True) -> Optional[Any]:
        """
        Look up a qualified symbol (e.g., io.File, collections.Map).

        The qualifier is resolved as:
        1. A module alias (from `import std.io as io`)
        2. A module name (from `import std.io` -> accessible as `io.File`)

        Args:
            qualifier: The module name/alias (e.g., "io")
            name: The symbol name (e.g., "File")
            in_module: The module context for the lookup
            check_visibility: If True, only return PUBLIC symbols
        """
        module_path = in_module or self.current_module

        def is_visible(symbol) -> bool:
            if not check_visibility:
                return True
            return hasattr(symbol, 'visibility') and symbol.visibility == Visibility.PUBLIC

        # Check module aliases
        if module_path in self.module_aliases:
            if qualifier in self.module_aliases[module_path]:
                target_module = self.module_aliases[module_path][qualifier]
                if target_module in self.modules:
                    ns = self.modules[target_module]
                    # Try each symbol type, checking visibility
                    if result := ns.lookup_struct(name):
                        if is_visible(result):
                            return result
                    if result := ns.lookup_enum(name):
                        if is_visible(result):
                            return result
                    if result := ns.lookup_function(name):
                        if is_visible(result):
                            return result
                    if result := ns.lookup_interface(name):
                        if is_visible(result):
                            return result

        return None

    def resolve_module_path(self, path: List[str],
                           from_module: Tuple[str, ...]) -> Tuple[str, ...]:
        """
        Resolve a potentially relative module path to absolute.

        Handles:
        - 'package.foo' -> resolve from package root
        - 'parent.foo' -> resolve relative to parent
        - 'foo.bar' -> absolute path
        """
        if not path:
            return ()

        if path[0] == 'package':
            # Package-relative: strip 'package' prefix
            return tuple(path[1:])

        if path[0] == 'parent':
            # Parent-relative
            if len(from_module) > 1:
                return from_module[:-1] + tuple(path[1:])
            return tuple(path[1:])

        return tuple(path)

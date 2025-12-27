"""
Saw Language Namespace
Unified symbol table for all declarations.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum, auto
from ast_nodes import SawType, TypeKind, Function, Struct, Enum as SawEnum, Extension, TypeParameter


class SymbolKind(Enum):
    FUNCTION = auto()
    STRUCT = auto()
    ENUM = auto()
    METHOD = auto()
    INTERFACE = auto()
    TYPE_ALIAS = auto()


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


@dataclass
class TypeAliasSymbol:
    """Symbol for a type alias."""
    kind: SymbolKind = SymbolKind.TYPE_ALIAS
    aliased_type: Optional[SawType] = None


class Namespace:
    """Unified symbol table for all declarations.

    This consolidates all type/function/method lookups into a single
    source of truth that both the type checker and code generator use.
    """

    def __init__(self):
        # Core symbol tables
        self.functions: Dict[str, FunctionSymbol] = {}
        self.structs: Dict[str, StructSymbol] = {}
        self.enums: Dict[str, EnumSymbol] = {}
        self.interfaces: Dict[str, InterfaceSymbol] = {}
        self.type_aliases: Dict[str, TypeAliasSymbol] = {}

        # Type conformances: type_name -> {interface_name -> {assoc_type_name -> SawType}}
        self.conformances: Dict[str, Dict[str, Dict[str, SawType]]] = {}

        # Generic AST storage for instantiation
        self.generic_functions: Dict[str, Function] = {}
        self.generic_structs: Dict[str, Struct] = {}
        self.generic_enums: Dict[str, SawEnum] = {}
        self.generic_extensions: Dict[str, List[Extension]] = {}

        # Tracks which monomorphized instantiations have been generated
        self.instantiated: set = set()

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
    # Generic Instantiation Tracking
    # =========================================================================

    def mark_instantiated(self, mangled_name: str):
        """Mark a generic instantiation as generated."""
        self.instantiated.add(mangled_name)

    def is_instantiated(self, mangled_name: str) -> bool:
        """Check if a generic instantiation has been generated."""
        return mangled_name in self.instantiated

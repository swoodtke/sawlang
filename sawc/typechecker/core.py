"""
Saw Language Type Checker
Performs type checking and semantic analysis on the AST.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from ast_nodes import (
    Program, Function, Block, Statement, Expression,
    LetStatement, AssignStatement, ReturnStatement, ExpressionStatement,
    WhileExpr, BreakStatement, ContinueStatement, ForLoop, RangeExpr,
    IntLiteral, FloatLiteral, BoolLiteral, StringLiteral, StringInterpolation, Identifier,
    BinaryOp, UnaryOp, MoveExpr, CastExpr, FunctionCall, IfExpr, IfLetExpr,
    TupleLiteral, TupleIndex, ArrayLiteral, ArrayIndex,
    MemberAccess, StructInit,
    NoneLiteral, ForceUnwrap, NilCoalesce, OptionalChain,
    GuardLetStatement,
    Struct, StructField,
    Enum, EnumVariant, EnumInit, MatchExpr, MatchArm,
    Extension, Method, MethodCall, SelfExpr,
    Trait, TraitMethod, AssociatedType, TypeAssignment, TypeDefinition,
    ExternFunction, ExternBlock,
    SawType, TypeKind, Parameter, Argument, TypeParameter,
    ClosureExpr, ClosureParam,
    ImportDecl
)
from errors import ErrorReporter, ErrorKind
from namespace import (
    Namespace, SymbolKind,
    FunctionSymbol, StructSymbol, EnumSymbol, TraitSymbol, TypeAliasSymbol,
    TraitMethodSymbol
)
from .types import TypeUtilsMixin
from .registration import RegistrationMixin
from .statements import StatementsMixin
from .expressions import ExpressionsMixin


@dataclass
class VariableInfo:
    """Information about a variable in scope."""
    type: SawType
    mutable: bool
    line: int
    column: int


@dataclass
class FunctionInfo:
    """Information about a function."""
    param_types: List[SawType]
    return_type: SawType
    param_names: List[str]
    type_params: List[TypeParameter] = field(default_factory=list)  # For generic functions
    is_variadic: bool = False  # True for variadic functions like printf, open


@dataclass
class StructInfo:
    """Information about a struct."""
    name: str
    fields: Dict[str, SawType]  # field_name -> type
    field_order: List[str]  # preserve declaration order
    line: int = 0
    column: int = 0
    methods: Dict[str, 'MethodInfo'] = field(default_factory=dict)  # method_name -> info
    type_params: List[TypeParameter] = field(default_factory=list)  # For generic structs
    # Specialized methods for specific type arguments (e.g., extension Vector<String>)
    # Key: tuple of type arg strings like ("String",), Value: method_name -> MethodInfo
    specialized_methods: Dict[Tuple[str, ...], Dict[str, 'MethodInfo']] = field(default_factory=dict)


@dataclass
class EnumInfo:
    """Information about an enum."""
    name: str
    variants: Dict[str, List[Tuple[str, SawType]]]  # variant_name -> [(param_name, type), ...]
    variant_order: List[str]  # preserve declaration order
    type_params: List[TypeParameter] = field(default_factory=list)  # For generic enums


@dataclass
class MethodInfo:
    """Information about a method."""
    struct_name: str
    method_name: str
    param_types: List[SawType]  # Includes self for instance methods
    return_type: SawType
    param_names: List[str]
    self_mutable: bool  # True if 'var self'
    is_init: bool = False
    is_static: bool = False  # True for methods without 'self' parameter
    default_values: List[Optional['Expression']] = field(default_factory=list)  # Default values for params


@dataclass
class TraitMethodInfo:
    """Information about a method signature in a trait."""
    name: str
    param_types: List[SawType]  # Includes self
    return_type: SawType
    param_names: List[str]
    self_mutable: bool = False  # True if 'var self'


@dataclass
class TraitInfo:
    """Information about a trait."""
    name: str
    methods: Dict[str, TraitMethodInfo]  # method_name -> info
    associated_types: List[str] = field(default_factory=list)  # Associated type names (e.g., ["Item"])
    parent_traits: List[str] = field(default_factory=list)  # Parent trait names


class Scope:
    """A lexical scope containing variable bindings."""

    def __init__(self, parent: Optional['Scope'] = None):
        self.parent = parent
        self.variables: Dict[str, VariableInfo] = {}

    def define(self, name: str, info: VariableInfo) -> bool:
        """Define a variable in this scope. Returns False if already defined."""
        if name in self.variables:
            return False
        self.variables[name] = info
        return True

    def lookup(self, name: str) -> Optional[VariableInfo]:
        """Look up a variable, checking parent scopes."""
        if name in self.variables:
            return self.variables[name]
        if self.parent:
            return self.parent.lookup(name)
        return None

    def lookup_local(self, name: str) -> Optional[VariableInfo]:
        """Look up a variable only in this scope."""
        return self.variables.get(name)


class TypeChecker(ExpressionsMixin, StatementsMixin, RegistrationMixin, TypeUtilsMixin):
    """Type checks a Saw program."""

    def __init__(self, reporter: ErrorReporter):
        self.reporter = reporter
        self.structs: Dict[str, StructInfo] = {}
        self.enums: Dict[str, EnumInfo] = {}
        self.traits: Dict[str, TraitInfo] = {}
        self.functions: Dict[str, FunctionInfo] = {}
        self.current_scope: Scope = Scope()
        self.current_function: Optional[Function] = None
        self.current_method: Optional['Method'] = None  # Track current method for 'self'
        # Type substitution map for specialized extensions (e.g., {"T": String})
        self.current_type_subst: Dict[str, SawType] = {}
        # Track return statements found in current function
        self.found_return_with_value: bool = False
        # Track loop nesting depth for break/continue validation
        self.loop_depth: int = 0
        # Track break value types for each loop level
        # Each entry is (expected_type: Optional[SawType], is_infinite: bool, has_break: bool)
        self.loop_break_info: List[Tuple[Optional[SawType], bool, bool]] = []
        # Track which types implement which traits
        self.type_conformances: Dict[str, List[str]] = {}  # type_name -> [trait_names]
        # Track associated type assignments: (type_name, trait_name) -> {assoc_type_name: SawType}
        self.type_assignments: Dict[Tuple[str, str], Dict[str, SawType]] = {}
        # Type aliases: name -> SawType
        self.type_aliases: Dict[str, SawType] = {}
        # Track moved variables for use-after-move detection
        self.moved_variables: set[str] = set()
        # Track if we're inside a try-catch block (errors go to catch, not caller)
        self.in_try_catch_block: bool = False

        # Unified namespace (Phase 0 of module system)
        # Populated in parallel with legacy dicts during migration
        self.namespace = Namespace()

        # Current module path during multi-module type checking
        self.current_module_path: Tuple[str, ...] = ()

        # Register built-in functions
        self._register_builtins()

    def check(self, program: Program) -> bool:
        """Type check the entire program. Returns True if no errors."""
        # Validate: exports are only allowed in init.saw files
        exports = getattr(program, 'exports', [])
        if exports:
            source_path = getattr(program, 'source_path', None)
            is_init_saw = source_path and source_path.endswith('init.saw')
            if not is_init_saw:
                for exp in exports:
                    self.reporter.error(
                        ErrorKind.SYNTAX,
                        "`export` statements are only allowed in init.saw files",
                        exp.line, exp.column,
                        hint="use `public` visibility modifier to expose symbols from regular modules"
                    )

        # First pass: register type definitions (aliases)
        for type_def in program.type_definitions:
            self._register_type_definition(type_def)

        # Second pass: collect struct definitions
        for struct in program.structs:
            self._register_struct(struct)

        # Third pass: collect enum definitions
        for enum in program.enums:
            self._register_enum(enum)

        # Fourth pass: collect trait definitions
        for trait in program.traits:
            self._register_trait(trait)

        # Fifth pass: register extensions and their methods
        for extension in program.extensions:
            self._register_extension(extension)

        # Fifth-b pass: check resource management containment rules
        self._check_no_copy_containment()
        self._check_custom_copy_containment()
        self._check_deinit_containment()

        # Register extern functions (FFI)
        for extern_block in program.extern_blocks:
            for extern_func in extern_block.functions:
                self._register_extern_function(extern_func)

        # Sixth pass: collect function signatures
        for func in program.functions:
            self._register_function(func)

        # Check for main function
        if "main" not in self.functions:
            self.reporter.error(
                ErrorKind.UNDEFINED_FUNCTION,
                "no `main` function found",
                1, 1,
                hint="add a `fn main() { }` function as the entry point"
            )

        # Seventh pass: type check function bodies
        for func in program.functions:
            self._check_function(func)

        # Eighth pass: type check method bodies
        for extension in program.extensions:
            self._check_extension(extension)

        return not self.reporter.has_errors()

    def check_module(
        self,
        module_ast: Program,
        module_path: Tuple[str, ...],
        checked_modules: Dict[Tuple[str, ...], Tuple[Program, 'Namespace']],
        builtin_namespace: 'Namespace',
        parent_namespace: Optional['Namespace'] = None,
        is_entry: bool = False
    ) -> Optional['Namespace']:
        """
        Type check a single module with its own namespace.

        This implements per-module type checking where each module is type-checked
        in isolation with only its imports visible. This is the Phase 5.0 approach.

        Args:
            module_ast: The parsed Program AST for this module
            module_path: The module's path as a tuple (e.g., ("std", "io"))
            checked_modules: Dict of already type-checked modules (path -> (ast, namespace))
            builtin_namespace: Pre-populated namespace with builtins
            parent_namespace: Optional parent module's namespace for nested modules
            is_entry: True if this is the entry module (should check for main)

        Returns:
            The module's namespace if successful, None on error
        """
        from namespace import (
            Namespace, FunctionSymbol, StructSymbol, EnumSymbol,
            TraitSymbol, TypeAliasSymbol, TraitMethodSymbol
        )
        from ast_nodes import Visibility

        # Create a fresh namespace for this module
        ns = Namespace(module_path=module_path)
        ns.package_root = builtin_namespace.package_root

        # Clone builtins into this module's namespace (all directly accessible)
        ns.merge_into(builtin_namespace)
        ns.directly_accessible = set(builtin_namespace.directly_accessible)

        # Inherit from parent if this is a nested module
        if parent_namespace:
            for name, sym in parent_namespace.structs.items():
                if sym.visibility == Visibility.PUBLIC:
                    if name not in ns.structs:
                        ns.register_struct(name, sym)
                    ns.make_accessible(name)
            for name, sym in parent_namespace.enums.items():
                if sym.visibility == Visibility.PUBLIC:
                    if name not in ns.enums:
                        ns.register_enum(name, sym)
                    ns.make_accessible(name)
            for name, sym in parent_namespace.functions.items():
                if sym.visibility == Visibility.PUBLIC:
                    if name not in ns.functions:
                        ns.register_function(name, sym)
                    ns.make_accessible(name)
            for name, sym in parent_namespace.traits.items():
                if sym.visibility == Visibility.PUBLIC:
                    if name not in ns.traits:
                        ns.register_trait(name, sym)
                    ns.make_accessible(name)

        # Process imports - register imported modules in this namespace
        for imp in getattr(module_ast, 'imports', []):
            imp_path = tuple(imp.path)
            # Handle package/parent prefixes
            if imp_path and imp_path[0] == 'package':
                imp_path = imp_path[1:]
            elif imp_path and imp_path[0] == 'parent':
                # Resolve relative to current module
                if len(module_path) > 0:
                    imp_path = module_path[:-1] + imp_path[1:]
                else:
                    imp_path = imp_path[1:]

            if imp.is_glob:
                # import foo.* -> make all public symbols directly accessible
                base_path = imp_path[:-1] if imp_path and imp_path[-1] == '*' else imp_path
                if base_path in checked_modules:
                    source_ast, source_ns = checked_modules[base_path]
                    for name, sym in source_ns.structs.items():
                        if sym.visibility == Visibility.PUBLIC:
                            ns.make_accessible(name)
                    for name, sym in source_ns.enums.items():
                        if sym.visibility == Visibility.PUBLIC:
                            ns.make_accessible(name)
                    for name, sym in source_ns.functions.items():
                        if sym.visibility == Visibility.PUBLIC:
                            ns.make_accessible(name)
                    for name, sym in source_ns.traits.items():
                        if sym.visibility == Visibility.PUBLIC:
                            ns.make_accessible(name)
            elif imp.symbols:
                # import foo.{A, B} -> make specific symbols directly accessible
                if imp_path in checked_modules:
                    for sym_name in imp.symbols:
                        ns.make_accessible(sym_name)
            else:
                # import foo.bar -> register module for qualified access
                if imp_path in checked_modules:
                    alias = imp.alias or (imp.path[-1] if imp.path else "")
                    _, source_ns = checked_modules[imp_path]
                    from namespace import ModuleSymbol
                    ns.modules[alias] = ModuleSymbol(
                        namespace=source_ns,
                        path=list(imp_path),
                        visibility=Visibility.PRIVATE  # Imports are private
                    )

        # Handle external module declarations (`module foo`)
        # These are registered for qualified access just like imports
        for mod_decl in getattr(module_ast, 'module_decls', []):
            if not mod_decl.is_inline:
                # External module declaration
                mod_path = (mod_decl.name,)
                if mod_path in checked_modules:
                    _, source_ns = checked_modules[mod_path]
                    from namespace import ModuleSymbol
                    mod_visibility = Visibility.PUBLIC if mod_decl.is_public else Visibility.PRIVATE
                    ns.modules[mod_decl.name] = ModuleSymbol(
                        namespace=source_ns,
                        path=list(mod_path),
                        visibility=mod_visibility
                    )

        # Register this module's own declarations

        # Save old state
        old_namespace = self.namespace
        old_module_path = self.current_module_path
        self.namespace = ns
        self.current_module_path = module_path

        # Register type definitions
        for type_def in module_ast.type_definitions:
            self._register_type_definition(type_def)
            ns.make_accessible(type_def.name)

        # Register structs
        for struct in module_ast.structs:
            self._register_struct(struct)
            ns.make_accessible(struct.name)

        # Register enums
        for enum in module_ast.enums:
            self._register_enum(enum)
            ns.make_accessible(enum.name)

        # Register traits
        for trait in module_ast.traits:
            self._register_trait(trait)
            ns.make_accessible(trait.name)

        # Register extensions
        for extension in module_ast.extensions:
            self._register_extension(extension)

        # Check resource containment rules
        self._check_no_copy_containment()
        self._check_custom_copy_containment()
        self._check_deinit_containment()

        # Register extern functions
        for extern_block in module_ast.extern_blocks:
            for extern_func in extern_block.functions:
                self._register_extern_function(extern_func)
                ns.make_accessible(extern_func.name)

        # Register functions
        for func in module_ast.functions:
            self._register_function(func)
            ns.make_accessible(func.name)

        # Handle inline module declarations BEFORE type-checking function bodies
        # This ensures that inline modules are available for use in the current module
        for mod_decl in getattr(module_ast, 'module_decls', []):
            if mod_decl.is_inline and mod_decl.body:
                inline_path = module_path + (mod_decl.name,)
                inline_ns = self.check_module(
                    mod_decl.body,
                    inline_path,
                    checked_modules,
                    builtin_namespace,
                    parent_namespace=ns,
                    is_entry=False
                )
                if inline_ns is None:
                    # Error in inline module
                    self.namespace = old_namespace
                    self.current_module_path = old_module_path
                    return None

                # Register the inline module in this module's namespace
                from namespace import ModuleSymbol
                mod_visibility = Visibility.PUBLIC if mod_decl.is_public else Visibility.PRIVATE
                ns.modules[mod_decl.name] = ModuleSymbol(
                    namespace=inline_ns,
                    path=list(inline_path),
                    visibility=mod_visibility
                )

        # Check for main function (only for entry module)
        if is_entry and "main" not in self.functions:
            self.reporter.error(
                ErrorKind.UNDEFINED_FUNCTION,
                "no `main` function found",
                1, 1,
                hint="add a `fn main() { }` function as the entry point"
            )

        # Enable import checking for this module
        ns.enable_import_checking()

        # Type check function bodies
        for func in module_ast.functions:
            self._check_function(func)

        # Type check method bodies
        for extension in module_ast.extensions:
            self._check_extension(extension)

        # Restore old state
        self.namespace = old_namespace
        self.current_module_path = old_module_path

        if self.reporter.has_errors():
            return None

        return ns

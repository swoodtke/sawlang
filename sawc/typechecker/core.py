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
from .effects import EffectsMixin


@dataclass
class VariableInfo:
    """Information about a variable in scope."""
    type: SawType
    mutable: bool
    line: int
    column: int


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


class TypeChecker(ExpressionsMixin, StatementsMixin, RegistrationMixin, TypeUtilsMixin, EffectsMixin):
    """Type checks a Saw program."""

    def __init__(self, reporter: ErrorReporter, freestanding: bool = False):
        self.reporter = reporter
        # Freestanding profile (design 19/20): gates hosted-only facilities such
        # as Float formatting in print (dtoa is not available without libc).
        self.freestanding = freestanding
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
        # Per-function, scope-aware move state for use-after-move detection.
        # Keyed by id() of the binding's VariableInfo (its identity), so that
        # same-named bindings in different functions/scopes never interact and
        # a `let`/`var` shadow gets fresh state. The VariableInfo object is kept
        # alive in the value tuple, so the id() key can never be reused.
        # value = (var_info, name, move_line, move_column)
        self.moved_bindings: Dict[int, Tuple['VariableInfo', str, int, int]] = {}
        # Structs whose copy() is compiler-derived (memberwise), checked for
        # NoCopy fields after all conformances are registered.
        self._derived_copy_structs: set[str] = set()
        # Structs/enums whose equals() (==) is compiler-derived (design 32),
        # checked for non-Equatable fields/payloads after all conformances are
        # registered.
        self._derived_equals_types: set[str] = set()
        # Structs/enums whose compare() (< <= > >=) is compiler-derived
        # (design 48), checked for non-Comparable fields/payloads and the
        # Equatable requirement after all conformances are registered.
        self._derived_compare_types: set[str] = set()
        # Structs/enums whose hash() is compiler-derived (design 48), checked for
        # non-Hashable fields/payloads after all conformances are registered.
        self._derived_hash_types: set[str] = set()
        # Every type declaring `extension T: Comparable` / `Hashable` (derived or
        # custom): each must also conform to Equatable (the "requires Equatable"
        # rule), verified after all conformances are registered.
        self._comparable_types: set[str] = set()
        self._hashable_types: set[str] = set()
        # Track if we're inside a try-catch block (errors go to catch, not caller)
        self.in_try_catch_block: bool = False

        # design 22 effect system: whole-program suspend analysis state.
        self._effect_init()

        # Unified namespace (Phase 0 of module system)
        # Populated in parallel with legacy dicts during migration
        self.namespace = Namespace()

        # Current module path during multi-module type checking
        self.current_module_path: Tuple[str, ...] = ()

        # Register built-in functions
        self._register_builtins()

    def _get_current_source_file(self) -> Optional[str]:
        """Get the source file from the current method or function context."""
        if self.current_method and hasattr(self.current_method, 'source_file'):
            return self.current_method.source_file or None
        if self.current_function and hasattr(self.current_function, 'source_file'):
            return self.current_function.source_file or None
        return None

    def _error(self, kind: ErrorKind, message: str, line: int, column: int,
               hint: Optional[str] = None, source_file: Optional[str] = None):
        """Report an error with automatic source file detection.

        If source_file is not provided, attempts to determine it from the
        current method or function context.
        """
        if source_file is None:
            source_file = self._get_current_source_file()
        self.reporter.error(kind, message, line, column, hint, source_file)

    def _warning(self, kind: ErrorKind, message: str, line: int, column: int,
                 hint: Optional[str] = None, source_file: Optional[str] = None):
        """Report a warning with automatic source file detection."""
        if source_file is None:
            source_file = self._get_current_source_file()
        self.reporter.warning(kind, message, line, column, hint, source_file)

    def _validate_exports(self, program: Program):
        """`export` statements are only permitted in init.saw facade files.

        Applied on every compile path (single-file and per-module), so a stray
        `export` in a regular file is diagnosed regardless of whether the file
        also uses imports/modules.
        """
        exports = getattr(program, 'exports', [])
        if not exports:
            return
        source_path = getattr(program, 'source_path', None)
        if source_path is None:
            # Provenance unknown (e.g. an imported module AST that was not tagged
            # with its path); the entry file always carries source_path, so this
            # only skips imported modules — matching prior per-module behavior.
            return
        if source_path.endswith('init.saw'):
            return
        for exp in exports:
            self.reporter.error(
                ErrorKind.SYNTAX,
                "`export` statements are only allowed in init.saw files",
                exp.line, exp.column,
                hint="use `public` visibility modifier to expose symbols from regular modules"
            )

    def check(self, program: Program, require_main: bool = True) -> bool:
        """Type check the entire program. Returns True if no errors.

        Args:
            program: The AST to type check
            require_main: If True, error if no main() function (default for executables).
                         Set to False for library/object file compilation.
        """
        # Validate: exports are only allowed in init.saw files
        self._validate_exports(program)

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

        # Fifth-a.5 pass: validate `any Trait` existentials in all declared
        # signatures/fields (design 51 object safety + unsized discipline). Runs
        # after traits are registered so object safety is decidable.
        self._validate_existentials_in_program(program)

        # Fifth-b pass: check resource management containment rules
        self._check_no_copy_containment()
        self._check_implicit_copy_containment()
        self._check_explicit_copy_containment()
        self._check_copy_trait_exclusivity()
        self._check_derivable_copy()
        self._check_derivable_equals()
        self._check_derivable_compare()
        self._check_derivable_hash()
        self._check_ord_hash_require_equatable()
        self._check_deinit_containment()

        # Register extern functions (FFI)
        for extern_block in program.extern_blocks:
            for extern_func in extern_block.functions:
                self._register_extern_function(extern_func)

        # Sixth pass: collect function signatures
        for func in program.functions:
            self._register_function(func)

        # Sixth-b pass: register module-level statics (design 41). After
        # structs/enums/functions so a const initializer may reference them.
        for static in getattr(program, 'statics', []):
            self._register_static(static)

        # Overloading (design 55): now that every function/method signature is
        # registered, assign each member of a 2+ overload set its type-signature
        # codegen symbol (stamped on both the symbol and its AST node).
        self._stamp_overload_symbols()

        # Check for main function (only required for executables)
        if require_main and not self.namespace.has_function("main"):
            self.reporter.error(
                ErrorKind.UNDEFINED_FUNCTION,
                "no `main` function found",
                1, 1,
                hint="add a `func main() { }` function as the entry point, or use -c to compile as object file"
            )

        # Seventh pass: type check function bodies
        for func in program.functions:
            self._check_function(func)

        # Eighth pass: type check method bodies
        for extension in program.extensions:
            self._check_extension(extension)

        # Ninth pass: whole-program `sync` effect analysis (design 22).
        self.finalize_effects()

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
                # import foo.* -> copy all public symbols to local namespace
                base_path = imp_path[:-1] if imp_path and imp_path[-1] == '*' else imp_path
                if base_path in checked_modules:
                    source_ast, source_ns = checked_modules[base_path]
                    for name, sym in source_ns.structs.items():
                        if sym.visibility == Visibility.PUBLIC:
                            if name not in ns.structs:
                                ns.register_struct(name, sym)
                            ns.make_accessible(name)
                    for name, sym in source_ns.enums.items():
                        if sym.visibility == Visibility.PUBLIC:
                            if name not in ns.enums:
                                ns.register_enum(name, sym)
                            ns.make_accessible(name)
                    for name, sym in source_ns.functions.items():
                        if sym.visibility == Visibility.PUBLIC:
                            if name not in ns.functions:
                                ns.register_function(name, sym)
                            ns.make_accessible(name)
                    for name, sym in source_ns.traits.items():
                        if sym.visibility == Visibility.PUBLIC:
                            if name not in ns.traits:
                                ns.register_trait(name, sym)
                            ns.make_accessible(name)
                    for name, sym in source_ns.statics.items():
                        if sym.visibility == Visibility.PUBLIC:
                            if name not in ns.statics:
                                ns.register_static(name, sym)
                            ns.make_accessible(name)
            elif imp.symbols:
                # import foo.{A, B} -> copy specific symbols to local namespace
                if imp_path in checked_modules:
                    _, source_ns = checked_modules[imp_path]
                    for sym_name in imp.symbols:
                        # Copy the symbol from source to local namespace
                        if sym_name in source_ns.structs:
                            sym = source_ns.structs[sym_name]
                            if sym.visibility == Visibility.PUBLIC:
                                if sym_name not in ns.structs:
                                    ns.register_struct(sym_name, sym)
                                ns.make_accessible(sym_name)
                        elif sym_name in source_ns.enums:
                            sym = source_ns.enums[sym_name]
                            if sym.visibility == Visibility.PUBLIC:
                                if sym_name not in ns.enums:
                                    ns.register_enum(sym_name, sym)
                                ns.make_accessible(sym_name)
                        elif sym_name in source_ns.functions:
                            sym = source_ns.functions[sym_name]
                            if sym.visibility == Visibility.PUBLIC:
                                if sym_name not in ns.functions:
                                    ns.register_function(sym_name, sym)
                                ns.make_accessible(sym_name)
                        elif sym_name in source_ns.statics:
                            sym = source_ns.statics[sym_name]
                            if sym.visibility == Visibility.PUBLIC:
                                if sym_name not in ns.statics:
                                    ns.register_static(sym_name, sym)
                                ns.make_accessible(sym_name)
                        elif sym_name in source_ns.traits:
                            sym = source_ns.traits[sym_name]
                            if sym.visibility == Visibility.PUBLIC:
                                if sym_name not in ns.traits:
                                    ns.register_trait(sym_name, sym)
                                ns.make_accessible(sym_name)
                    # Also register module for qualified access to non-imported symbols
                    alias = imp.path[-1] if imp.path else ""
                    from namespace import ModuleSymbol
                    ns.modules[alias] = ModuleSymbol(
                        namespace=source_ns,
                        path=list(imp_path),
                        visibility=Visibility.PRIVATE
                    )
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

        # Validate: exports are only allowed in init.saw files (same rule as the
        # single-file path; enforced here so the unified pipeline still catches
        # a stray `export` in a regular entry/module file).
        self._validate_exports(module_ast)

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

        # Validate `any Trait` existentials in declared signatures (design 51).
        self._validate_existentials_in_program(module_ast)

        # Check resource containment rules
        self._check_no_copy_containment()
        self._check_implicit_copy_containment()
        self._check_explicit_copy_containment()
        self._check_copy_trait_exclusivity()
        self._check_derivable_copy()
        self._check_derivable_equals()
        self._check_derivable_compare()
        self._check_derivable_hash()
        self._check_ord_hash_require_equatable()
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

        # Register module-level statics (design 41). Accessible module-locally;
        # a `public` static is additionally visible to importers.
        for static in getattr(module_ast, 'statics', []):
            self._register_static(static)
            ns.make_accessible(static.name)

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

        # Overloading (design 55): stamp overload-set codegen symbols for this
        # module now that all its signatures are registered.
        self._stamp_overload_symbols()

        # Check for main function (only for entry module)
        if is_entry and not self.namespace.has_function("main"):
            self.reporter.error(
                ErrorKind.UNDEFINED_FUNCTION,
                "no `main` function found",
                1, 1,
                hint="add a `func main() { }` function as the entry point, or use -c to compile as object file"
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

        # Whole-program `sync` effect analysis (design 22). The entry module is
        # checked last, after every other module's bodies have contributed their
        # call-graph edges, so this runs once over the complete graph.
        if is_entry:
            self.finalize_effects()

        if self.reporter.has_errors():
            return None

        return ns

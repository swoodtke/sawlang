# Module System Implementation Plan for Saw

## Overview

Add a full module system with file-level namespaces, visibility modifiers, and config-based search paths.

## Status

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Unified Namespace | **COMPLETE** |
| 1 | Foundation (Basic Imports) | **COMPLETE** |
| 2 | Symbol-Level Imports | **COMPLETE** |
| 3 | Visibility System | **COMPLETE** |
| 4 | Module Declarations | **COMPLETE** |
| 4.5 | Per-Module Namespace Resolution | **COMPLETE** |
| 5 | Package Manifest & Module Facades | **COMPLETE** |

## Phased Implementation

### Phase 0: Unified Namespace ✅ COMPLETE

**Goal**: Consolidate all separate lookup tables into a single `Namespace` object that codegen consumes.

Currently codegen has ~15 separate dictionaries:
- `self.functions` - LLVM functions
- `self.struct_types` - (LLVM type, field_order)
- `self.enum_types` - (LLVM type, variant_tags, variant_info)
- `self.function_return_types` - function name → SawType
- `self.method_return_types` - (struct, method) → SawType
- `self.static_methods` - set of (struct, method)
- `self.method_defaults` - default parameter values
- `self.generic_functions`, `self.generic_structs`, `self.generic_extensions`
- `self.type_aliases`, `self.type_conformances`, `self.type_assignments`
- `self.struct_field_types`, `self.interfaces`

#### 0.1 New Namespace Class (`sawc/namespace.py`)

```python
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum, auto
from ast_nodes import SawType, Function, Struct, Enum as SawEnum, Extension

class SymbolKind(Enum):
    FUNCTION = auto()
    STRUCT = auto()
    ENUM = auto()
    METHOD = auto()      # Instance, static, and init methods (use is_static/is_init flags)
    INTERFACE = auto()
    TYPE_ALIAS = auto()

@dataclass
class FunctionSymbol:
    kind: SymbolKind = SymbolKind.FUNCTION
    param_types: List[SawType] = field(default_factory=list)
    param_names: List[str] = field(default_factory=list)
    return_type: Optional[SawType] = None
    type_params: List[str] = field(default_factory=list)  # For generics
    defaults: List[Optional[Any]] = field(default_factory=list)
    is_static: bool = False  # True for static methods
    is_init: bool = False    # True for init methods
    self_mutable: bool = False  # True for 'var self'
    ast_node: Optional[Function] = None  # For generic instantiation
    # Filled by codegen:
    llvm_func: Optional[Any] = None

@dataclass
class StructSymbol:
    kind: SymbolKind = SymbolKind.STRUCT
    fields: Dict[str, SawType] = field(default_factory=dict)
    field_order: List[str] = field(default_factory=list)
    type_params: List[str] = field(default_factory=list)
    methods: Dict[str, 'FunctionSymbol'] = field(default_factory=dict)  # All methods (use .is_static flag)
    init_methods: Dict[str, 'FunctionSymbol'] = field(default_factory=dict)  # keyed by param signature
    conformances: List[str] = field(default_factory=list)  # interface names
    ast_node: Optional[Struct] = None
    # Filled by codegen:
    llvm_type: Optional[Any] = None

@dataclass
class EnumSymbol:
    kind: SymbolKind = SymbolKind.ENUM
    variants: Dict[str, List[Tuple[str, SawType]]] = field(default_factory=dict)  # variant -> [(param, type)]
    type_params: List[str] = field(default_factory=list)
    ast_node: Optional[SawEnum] = None
    # Filled by codegen:
    llvm_type: Optional[Any] = None
    variant_tags: Optional[Dict[str, int]] = None

@dataclass
class InterfaceSymbol:
    kind: SymbolKind = SymbolKind.INTERFACE
    methods: Dict[str, FunctionSymbol] = field(default_factory=dict)
    associated_types: List[str] = field(default_factory=list)
    parent_interfaces: List[str] = field(default_factory=list)

@dataclass
class TypeAliasSymbol:
    kind: SymbolKind = SymbolKind.TYPE_ALIAS
    aliased_type: SawType = None

class Namespace:
    """Unified symbol table for all declarations."""

    def __init__(self):
        self.functions: Dict[str, FunctionSymbol] = {}
        self.structs: Dict[str, StructSymbol] = {}
        self.enums: Dict[str, EnumSymbol] = {}
        self.interfaces: Dict[str, InterfaceSymbol] = {}
        self.type_aliases: Dict[str, TypeAliasSymbol] = {}

        # Type conformances: type_name -> {interface -> {assoc_type -> concrete_type}}
        self.conformances: Dict[str, Dict[str, Dict[str, SawType]]] = {}

        # Generic instantiation tracking
        self.instantiated: set = set()  # mangled names already generated

    # === Lookup Methods ===

    def lookup_function(self, name: str) -> Optional[FunctionSymbol]:
        return self.functions.get(name)

    def lookup_struct(self, name: str) -> Optional[StructSymbol]:
        return self.structs.get(name)

    def lookup_enum(self, name: str) -> Optional[EnumSymbol]:
        return self.enums.get(name)

    def lookup_method(self, struct_name: str, method_name: str) -> Optional[FunctionSymbol]:
        struct = self.structs.get(struct_name)
        if struct:
            return struct.methods.get(method_name)
        return None

    def lookup_type(self, name: str) -> Optional[SawType]:
        """Resolve a type name to its definition."""
        if name in self.type_aliases:
            return self.type_aliases[name].aliased_type
        if name in self.structs:
            return SawType(kind=TypeKind.STRUCT, struct_name=name)
        if name in self.enums:
            return SawType(kind=TypeKind.ENUM, enum_name=name)
        return None

    def get_return_type(self, func_name: str) -> Optional[SawType]:
        if func_name in self.functions:
            return self.functions[func_name].return_type
        return None

    def get_method_return_type(self, struct_name: str, method_name: str) -> Optional[SawType]:
        method = self.lookup_method(struct_name, method_name)
        return method.return_type if method else None

    def is_static_method(self, struct_name: str, method_name: str) -> bool:
        method = self.lookup_method(struct_name, method_name)
        return method.is_static if method else False
```

#### 0.2 Type Checker Populates Namespace

Modify `TypeChecker` to build a `Namespace` instead of its own dicts:

```python
class TypeChecker:
    def __init__(self, reporter: ErrorReporter):
        self.reporter = reporter
        self.namespace = Namespace()  # NEW: unified namespace
        self.current_scope: Scope = Scope()
        # ... other fields ...

    def check(self, program: Program) -> bool:
        # Pass 1: Type definitions → namespace.type_aliases
        for type_def in program.type_definitions:
            self.namespace.type_aliases[type_def.name] = TypeAliasSymbol(
                aliased_type=type_def.defined_type
            )

        # Pass 2: Structs → namespace.structs
        for struct in program.structs:
            self.namespace.structs[struct.name] = StructSymbol(
                fields={f.name: f.type for f in struct.fields},
                field_order=[f.name for f in struct.fields],
                type_params=[tp.name for tp in struct.type_params],
                ast_node=struct if struct.type_params else None
            )

        # Pass 3: Enums → namespace.enums
        for enum in program.enums:
            self.namespace.enums[enum.name] = EnumSymbol(
                variants={v.name: v.associated_types for v in enum.variants},
                type_params=[tp.name for tp in enum.type_params],
                ast_node=enum if enum.type_params else None
            )

        # Pass 4: Interfaces → namespace.interfaces
        for iface in program.interfaces:
            self.namespace.interfaces[iface.name] = InterfaceSymbol(
                methods={m.name: FunctionSymbol(...) for m in iface.methods},
                associated_types=[at.name for at in iface.associated_types],
                parent_interfaces=iface.parent_interfaces
            )

        # Pass 5: Extensions → struct.methods (all methods in one dict)
        for ext in program.extensions:
            struct_sym = self.namespace.structs[ext.struct_name]
            for method in ext.methods:
                sym = FunctionSymbol(
                    kind=SymbolKind.METHOD,
                    param_types=[p.type for p in method.parameters],
                    param_names=[p.name for p in method.parameters],
                    return_type=method.return_type,
                    is_static=method.is_static,
                    is_init=method.is_init,
                    self_mutable=method.self_mutable,
                    ast_node=method
                )
                if method.is_init:
                    # Init methods keyed by param signature for overload resolution
                    key = "_".join(p.name for p in method.parameters if p.name != "self")
                    struct_sym.init_methods[key] = sym
                else:
                    # Regular and static methods in same dict
                    struct_sym.methods[method.name] = sym

            # Track conformances
            for iface_name in ext.conformances:
                if ext.struct_name not in self.namespace.conformances:
                    self.namespace.conformances[ext.struct_name] = {}
                self.namespace.conformances[ext.struct_name][iface_name] = {
                    ta.name: ta.assigned_type for ta in ext.type_assignments
                }

        # Pass 6: Functions → namespace.functions
        for func in program.functions:
            self.namespace.functions[func.name] = FunctionSymbol(
                param_types=[p.type for p in func.parameters],
                param_names=[p.name for p in func.parameters],
                return_type=func.return_type,
                type_params=[tp.name for tp in func.type_params],
                ast_node=func if func.type_params else None
            )

        # Pass 7: Type check function/method bodies (unchanged)
        ...

        return not self.reporter.has_errors()
```

#### 0.3 Codegen Consumes Namespace

Modify `CodeGenerator.__init__` to receive namespace:

```python
class CodeGenerator:
    def __init__(self, namespace: Namespace):
        self.namespace = namespace

        # LLVM setup (unchanged)
        binding.initialize()
        ...

        # REMOVE all these separate dicts (use namespace instead):
        # - self.functions → namespace.functions[name].llvm_func
        # - self.struct_types → namespace.structs[name].llvm_type
        # - self.enum_types → namespace.enums[name].llvm_type
        # - self.function_return_types → namespace.get_return_type()
        # - self.method_return_types → namespace.get_method_return_type()
        # - self.static_methods → namespace.lookup_method().is_static
        # - self.generic_functions → namespace.functions[name].ast_node
        # - self.generic_structs → namespace.structs[name].ast_node
        # - self.type_aliases → namespace.type_aliases
        # - self.type_conformances → namespace.conformances
        # - self.struct_field_types → namespace.structs[name].fields
        # - self.interfaces → namespace.interfaces

        # KEEP these (runtime state, not symbol info):
        self.builder: ir.IRBuilder = None
        self.variables: dict = {}  # local variable allocas
        self.variable_types: dict = {}
        self.loop_stack: list = []
        self.cleanup_stack: list = []
        self.moved_variables: set = set()
        self.string_constants: dict = {}
        self.type_param_context: dict = {}
```

#### 0.4 Update sawc.py Pipeline

```python
def compile_saw(source_path, output_path, verbose=False):
    # ... parse ...

    # Type check (builds namespace)
    reporter = ErrorReporter(source, source_path)
    typechecker = TypeChecker(reporter)
    if not typechecker.check(ast):
        reporter.print_all()
        sys.exit(1)

    # Pass namespace to codegen
    codegen = CodeGenerator(typechecker.namespace)  # NEW
    llvm_ir = codegen.generate(ast)
    ...
```

#### 0.5 Migration Strategy

1. Create `namespace.py` with all dataclasses
2. Add `self.namespace = Namespace()` to TypeChecker
3. Populate namespace in parallel with existing dicts (both work)
4. Update codegen to read from namespace (with fallback to old dicts)
5. Remove old dicts from TypeChecker once codegen fully migrated
6. Remove old dicts from CodeGenerator

#### 0.6 Benefits

- **Single source of truth** for all symbol information
- **Clean codegen interface** - just `namespace.lookup_*()` methods
- **Natural extension point** for modules - namespace per module later
- **Reduced coupling** between TypeChecker and CodeGenerator
- **Simpler debugging** - one place to inspect all symbols

#### 0.7 Implementation Summary (Completed)

**Commit**: `ef8e23c` - Add unified Namespace for symbol management

**Files created:**
- `sawc/namespace.py` - Symbol dataclasses and Namespace class

**Dicts migrated from codegen to namespace:**
| Dict | Namespace Method |
|------|-----------------|
| `type_aliases` | `lookup_type_alias()` |
| `function_return_types` | `get_return_type()` |
| `method_return_types` | `get_method_return_type()` |
| `static_methods` | `is_static_method()` |
| `type_conformances` | `get_conformances()` |
| `type_assignments` | `conformances[type][iface]` |
| `struct_field_types` | `get_struct_fields()` |
| `interfaces` | Removed (was unused) |

**Remaining in codegen** (runtime state, not symbol info):
- `functions`, `struct_types`, `enum_types` - LLVM types
- `generic_*` - AST for monomorphization
- `variables`, `variable_types` - local variable tracking
- `method_defaults` - could migrate later

---

### Phase 1: Foundation (Basic Imports) ✅ COMPLETE

**Goal**: `import std.vector` works, existing programs unaffected

#### 1.1 Lexer Changes (`sawc/lexer.py`)
Add tokens to `TokenType` enum:
```python
MODULE = auto()
IMPORT = auto()
PUBLIC = auto()
PACKAGE = auto()  # For public(package)
PARENT = auto()   # For parent.foo and public(parent)
```

Add to `KEYWORDS` dict:
```python
'module': TokenType.MODULE,
'import': TokenType.IMPORT,
'public': TokenType.PUBLIC,
'package': TokenType.PACKAGE,
'parent': TokenType.PARENT,
```

#### 1.2 AST Nodes (`sawc/ast_nodes.py`)
```python
class Visibility(Enum):
    PRIVATE = auto()   # Default
    PUBLIC = auto()
    PACKAGE = auto()   # public(package)
    PARENT = auto()    # public(parent)

@dataclass
class ImportDecl(ASTNode):
    path: List[str]              # ["std", "io"]
    symbols: Optional[List[str]] # {Map, Set} or None
    alias: Optional[str]         # as name
    is_glob: bool = False        # import foo.*
    line: int = 0
    column: int = 0

@dataclass
class ModuleDecl(ASTNode):
    name: str
    is_public: bool = False
    is_inline: bool = False
    body: Optional['Program'] = None  # For inline modules
    line: int = 0
    column: int = 0
```

Update `Program`:
```python
@dataclass
class Program(ASTNode):
    # ... existing fields ...
    imports: List[ImportDecl] = field(default_factory=list)
    module_decls: List[ModuleDecl] = field(default_factory=list)
    source_path: Optional[str] = None
    module_path: Optional[List[str]] = None
```

#### 1.3 Parser Changes (`sawc/parser.py`)
- Add `parse_import()` method for import syntax
- Add `parse_module_decl()` method
- Modify `parse()` to handle `import` and `module` at top level

#### 1.4 New Module Resolver (`sawc/module_resolver.py`)
```python
class ModuleResolver:
    def __init__(self, search_paths: List[str])
    def resolve_module(self, path: List[str]) -> ModuleInfo
    def find_module_file(self, path: List[str]) -> Optional[str]
    def build_dependency_graph(self, entry: ModuleInfo) -> List[ModuleInfo]
```

Search order:
1. Current file's directory
2. Package root (dir with Saw.toml)
3. `sawc/` (standard library)
4. Additional configured paths

File lookup for `import foo.bar`:
- Try `foo/bar.saw`
- Try `foo/bar/module.saw`

#### 1.5 Pipeline Changes (`sawc/sawc.py`)
```python
def compile_saw(source_path, output_path, verbose=False):
    # Check if program uses modules
    ast = parse_source(source, source_path)

    if ast.imports or ast.module_decls:
        # New multi-module path
        resolver = ModuleResolver(search_paths)
        modules = resolver.build_dependency_graph(ast)
        typechecker.check_modules(modules)
        codegen.generate_modules(modules)
    else:
        # Legacy single-file path (existing behavior)
        builtin_ast = load_builtins()
        merged = merge_programs(builtin_ast, ast)
        typechecker.check(merged)
        codegen.generate(merged)
```

#### 1.6 Implementation Summary (Completed)

**Files modified:**
- `sawc/lexer.py` - Added MODULE, IMPORT, PUBLIC tokens (PACKAGE/PARENT handled as identifiers)
- `sawc/ast_nodes.py` - Added Visibility enum, ImportDecl, ModuleDecl; updated Program
- `sawc/parser.py` - Added parse_import(), parse_module_decl(); updated parse()
- `sawc/sawc.py` - Added uses_modules() detection; updated merge_programs()

**Files created:**
- `sawc/module_resolver.py` - ModuleResolver class for module discovery

**Import syntax supported:**
| Syntax | Description |
|--------|-------------|
| `import std.vector` | Module import |
| `import std.io.{File, Directory}` | Symbol set import |
| `import std.collections as collections` | Aliased import |
| `import package.utils` | Package-relative import |
| `import parent.helpers` | Parent-relative import |
| `import foo.*` | Glob import |

**Module declaration syntax supported:**
| Syntax | Description |
|--------|-------------|
| `module name` | Sub-module declaration |
| `public module name` | Public sub-module |
| `module name { ... }` | Inline module |

**Key design decisions:**
- `package` and `parent` are NOT keywords - they are handled as special identifiers in import context only. This avoids conflicts with user code (e.g., a method named `parent`).
- Programs using modules are detected but still use the legacy compilation path for now
- All 131 existing tests pass (backward compatibility maintained)

---

### Phase 2: Symbol-Level Imports

**Goal**: All import syntax variants work

Syntax to support:
```saw
import std.io                      // Module import
import std.io.File                 // Single symbol
import std.collections.{Map, Set}  // Multiple symbols
import std.io as fileio            // Aliased module
import package.parser              // From package root
import parent.helpers              // From parent module
```

#### 2.1 Type Checker Changes (`sawc/typechecker.py`)
Add to `TypeChecker`:
```python
# Module-qualified symbol tables
self.qualified_structs: Dict[Tuple[str, ...], StructInfo] = {}
self.qualified_enums: Dict[Tuple[str, ...], EnumInfo] = {}
self.qualified_functions: Dict[Tuple[str, ...], FunctionInfo] = {}

# Current module context
self.current_module: List[str] = []

# Imported symbols in current module scope
self.imported_symbols: Dict[str, Tuple[List[str], str]] = {}
```

New method `check_modules()`:
- Pass 1: Register all type definitions from all modules
- Pass 2: Register all structs/enums
- Pass 3: Register interfaces
- Pass 4: Process imports for each module
- Pass 5: Register extensions
- Pass 6: Register function signatures
- Pass 7: Type check function bodies

Symbol lookup order:
1. Current scope variables
2. Current module's own declarations
3. Explicitly imported symbols
4. Builtins (print, etc.)

### Phase 3: Visibility System ✅ COMPLETE

**Goal**: Private by default, public exports

#### 3.1 Add visibility to declarations
Update AST nodes with `visibility: Visibility = Visibility.PRIVATE`:
- `Struct`, `Enum`, `Function`, `Interface`, `TypeDefinition`, `Extension`

#### 3.2 Parse visibility modifiers
```saw
public struct Point { ... }
public(package) func internal_api() { ... }
public(parent) func helper() { ... }
```

#### 3.3 Visibility checking in type checker
```python
def _check_visibility(self, visibility: Visibility, symbol_path: List[str]) -> bool:
    if visibility == Visibility.PUBLIC:
        return True
    if visibility == Visibility.PRIVATE:
        return symbol_path[:-1] == self.current_module
    if visibility == Visibility.PACKAGE:
        return self._same_package(symbol_path, self.current_module)
    if visibility == Visibility.PARENT:
        return self.current_module == symbol_path[:-2]
```

#### 3.4 Implementation Summary (Completed)

**Files modified:**
- `sawc/ast_nodes.py` - Added `visibility` field to Struct, Enum, Function, Interface, TypeDefinition, Extension
- `sawc/parser.py` - Added `_parse_visibility()` method and updated all declaration parsers
- `sawc/namespace.py` - Added `visibility` field to symbol types, `module_path` tracking, and visibility checking
- `sawc/typechecker.py` - Updated module symbol resolution to enforce visibility
- `test_runner.py` - Skip library modules in `examples/modules/` directory

**Visibility syntax supported:**
| Syntax | Visibility | Enforcement |
|--------|------------|-------------|
| (none) | `PRIVATE` | Only accessible within same module |
| `public` | `PUBLIC` | Accessible from anywhere |
| `public(package)` | `PACKAGE` | Accessible within same package |
| `public(parent)` | `PARENT` | Accessible only from parent module |

**Key implementation details:**
- `Namespace` now tracks `module_path` and `package_root` for visibility context
- `resolve()` and `_resolve_parts()` accept `accessor_module` for cross-module visibility checking
- `check_visibility()` implements all visibility rules with proper module path comparison
- Typechecker passes accessor module context when resolving cross-module symbols

**Tests added:**
- `visibility_public.saw` - Tests public visibility parsing and access
- `visibility_package.saw` - Tests public(package) visibility parsing
- `visibility_parent.saw` - Tests public(parent) visibility parsing
- `visibility_invalid.saw` - Tests error for invalid visibility modifiers
- `visibility_private_access_error.saw` - Verifies private functions are inaccessible
- `visibility_private_struct_error.saw` - Verifies private structs are inaccessible
- `visibility_package_access.saw` - Verifies public(package) IS accessible in same package
- `visibility_parent_access_error.saw` - Verifies public(parent) is NOT accessible from non-parent
- `visibility_parent_public_works.saw` - Verifies public symbols work in nested modules

**Test modules:**
- `examples/modules/utils.saw` - Mixed visibility (public, private, public(package))
- `examples/modules/nested/child.saw` - public(parent) and public symbols

**Total tests:** 145 (9 visibility tests)

---

### Phase 4: Module Declarations ✅ COMPLETE

**Goal**: User-defined modules, sub-modules

```saw
module parser           // Loads parser.saw
public module runtime   // Public sub-module
module helpers {        // Inline module
    public func util() { ... }
}
```

#### 4.1 Module loading from declarations
When `module parser` encountered:
- Look for `parser.saw` or `parser/module.saw`
- Parse and add to dependency graph

#### 4.2 Relative imports
- `package.foo` → from package root
- `parent.foo` → from parent module

#### 4.3 Implementation Summary (Completed)

**Files modified:**
- `sawc/sawc.py` - Added module declaration processing in `compile_with_modules()`
- `sawc/namespace.py` - Added `visibility` field to `ModuleSymbol`, updated `register_module_from_ast()` to accept visibility
- `test_runner.py` - Added `// EXPECT: skip` support for library modules

**Module declaration syntax supported:**
| Syntax | Description |
|--------|-------------|
| `module name` | External module - loads `name.saw` from source directory |
| `module name { ... }` | Inline module - symbols accessible as `name.Symbol` |
| `public module name` | Public module - visible to external importers |
| `public module name { ... }` | Public inline module |

**Key implementation details:**
- External modules are loaded from the same directory as the source file
- Inline module bodies are merged into the main AST for codegen
- Module symbols are only accessible via qualified access (`module.Symbol`)
- Direct access to inline module symbols produces helpful error message
- Module visibility (public vs private) is tracked and enforced

**Tests added:**
- `module_decl_inline.saw` - Inline module with qualified access
- `module_decl_inline_public.saw` - Public and private inline modules
- `module_decl_inline_direct_error.saw` - Verifies direct access is rejected
- `module_decl_external.saw` - External module declaration (`module name`)
- `myutils.saw` - Library module with `// EXPECT: skip` marker

**Total tests:** 149 (4 module declaration tests)

---

### Phase 4.5: Per-Module Namespace Resolution ✅ COMPLETE

**Problem**: When module A imports module B, and B has its own imports (e.g., `import utils`), B's code can't resolve its imports because we use a single global namespace for type-checking.

**Example of the bug:**
```saw
// lib_with_import.saw
import modules.utils  // B's own import

public func lib_double(n: Int) -> Int {
    utils.double(n)  // ERROR: 'utils' not found when lib_with_import is imported
}

// main.saw
import modules.lib_with_import  // Importing B causes B's code to fail type-check
```

**Current architecture (flawed):**
1. Parse all modules into `module_map`
2. Merge everything into one big AST
3. Type-check merged AST with single global namespace
4. Problem: Each module's imports aren't registered, so their code fails

**Intermediate fix:**
Pass `module_map` to `register_module_from_ast` so each module's namespace includes its own imports:

```python
def register_module_from_ast(self, alias, module_ast, path, visibility, module_map):
    # Create module namespace
    mod_ns = Namespace(module_path=path)

    # Register module's own symbols (structs, funcs, etc.)
    # ... existing code ...

    # NEW: Register module's imports in its namespace
    for imp in module_ast.imports:
        imp_path = tuple(imp.path)
        if imp_path in module_map:
            imp_alias = imp.alias or imp.path[-1]
            mod_ns.register_module_from_ast(
                imp_alias, module_map[imp_path], list(imp_path),
                visibility=Visibility.PRIVATE,  # Imports are private
                module_map=module_map
            )
```

**Result:**
- Each module can resolve its own imports ✓
- Imports are NOT exposed to importers (they're private to the module) ✓
- `lib_with_import.utils` correctly fails (utils not in lib_with_import's public API) ✓

#### 4.5.1 Implementation Summary (Completed)

**Files modified:**
- `sawc/namespace.py` - Added `module_map` parameter to `register_module_from_ast()`, registers module's imports in its namespace
- `sawc/namespace.py` - Added visibility checking for modules in `_resolve_parts()`
- `sawc/sawc.py` - Register transitive imports at top level for type-checking (Phase 4.5 block)
- `sawc/sawc.py` - Pass `module_map` to all `register_module_from_ast()` calls
- `sawc/typechecker.py` - Pass `check_visibility=True` when resolving cross-module symbols

**Key implementation details:**
- Each module's imports are registered in its own namespace with `visibility=Visibility.PRIVATE`
- Transitive imports are also registered at the top level for type-checking merged code
- Module visibility is now checked when resolving symbols via `namespace.resolve()`
- Private modules (including imports) are not accessible from external code

**Tests added:**
- `reexport_import_error.saw` - Verify imports aren't re-exported ✓
- `reexport_public_module.saw` - Verify public modules ARE re-exported ✓
- `reexport_private_module_error.saw` - Verify private modules aren't re-exported ✓

**Total tests:** 152 (3 new module re-export tests)

---

### Phase 5: Package Manifest, Module Facades & Per-Module Type Checking

**Goal**: Saw.toml support, `init.saw` facade modules, and proper per-module type checking

#### 5.0 Per-Module Type Checking (Proper Solution)

**Problem with Phase 4.5**: We still merge all code into one AST and type-check globally. This works but is architecturally messy.

**Proper solution**: Type-check each module separately, then merge for codegen.

```
Current flow (Phase 4.5):
  Parse all → Merge AST → Type-check merged → Codegen

Proper flow (Phase 5):
  Parse all → Type-check each module with its own namespace → Merge for codegen
```

**Implementation:**
1. Each `ModuleInfo` gets a `namespace` field populated during parsing
2. Type-check each module using its own namespace
3. Module's namespace includes:
   - Own symbols (structs, funcs, enums, interfaces)
   - Own imports (resolved from module_map)
   - Own inline modules
   - Access to parent module's public symbols (for nested modules)
4. After all modules type-check, merge for codegen

**Benefits:**
- Clean separation of concerns
- Each module is self-contained
- Errors reported with correct module context
- Foundation for incremental compilation

#### 5.1 Saw.toml Package Manifest

```toml
[package]
name = "my_app"
version = "0.1.0"

[dependencies]
# Future: external packages
```

Parse Saw.toml to find:
- Package root directory
- Package name for `package.` imports

#### 5.2 Module Facade with init.saw

**Problem**: Without a facade, your file structure IS your public API. Refactoring internal files breaks downstream users.

**Solution**: Optional `init.saw` file that defines the public API independently of file structure.

```
mylib/
  init.saw              # Optional - defines public API
  Saw.toml              # Package manifest
  internal/
    foobar.saw          # Contains FooImpl, BarImpl
    helpers.saw         # Internal utilities
  utils.saw             # Utility functions
```

**init.saw syntax:**

```saw
// mylib/init.saw - defines what users see when they `import mylib`

// Re-export with rename (hides internal path)
export internal.foobar.FooImpl as Foo    // Accessible as mylib.Foo
export internal.foobar.BarImpl as Bar    // Accessible as mylib.Bar

// Re-export entire module (flattens path)
export utils                              // Accessible as mylib.utils
                                          // NOT mylib.internal.utils

// Re-export all public symbols from a module (glob)
export internal.foobar.*                  // All public symbols at mylib.*

// Re-export with preserved structure
export internal.helpers as helpers        // Accessible as mylib.helpers
```

**Behavior:**

| Scenario | Result |
|----------|--------|
| `init.saw` exists | Only explicitly exported symbols are visible |
| `init.saw` missing | All public symbols exposed, file structure = API |
| `export foo.bar` | Exposed as `pkgname.bar` (path flattened) |
| `export foo.bar as baz` | Exposed as `pkgname.baz` (renamed) |
| `export foo.bar.*` | All public symbols from bar at `pkgname.*` |

**Example usage:**

```saw
// User code
import mylib

let f = mylib.Foo()           // Works - exported in init.saw
let b = mylib.Bar()           // Works - exported in init.saw
let h = mylib.helpers.util()  // Works - exported as helpers

// These FAIL - internal structure hidden:
let x = mylib.internal.foobar.FooImpl()  // Error
let y = mylib.internal.helpers.secret()   // Error
```

#### 5.3 Implementation Notes

**Files to modify:**
- `sawc/lexer.py` - Add EXPORT token
- `sawc/ast_nodes.py` - Add ExportDecl node
- `sawc/parser.py` - Add parse_export()
- `sawc/module_resolver.py` - Check for init.saw, build facade namespace
- `sawc/sawc.py` - Integrate facade resolution

**Resolution order:**
1. Look for `module_name/init.saw`
2. If exists, build namespace from export statements only
3. If missing, build namespace from all public symbols (current behavior)

#### 5.4 Implementation Summary (Completed)

**Files modified:**
- `sawc/lexer.py` - Added EXPORT token
- `sawc/ast_nodes.py` - Added ExportDecl node, updated Program with exports field
- `sawc/parser.py` - Added parse_export() method, updated parse() for export statements
- `sawc/module_resolver.py` - Added PackageManifest, ExportInfo, FacadeInfo dataclasses; added Saw.toml parsing and init.saw facade resolution
- `sawc/sawc.py` - Preserve exports in merge_programs()
- `sawc/typechecker.py` - Validate that export statements are only allowed in init.saw files

**Saw.toml parsing:**
- Simple TOML parser supports `[package]` section with `name` and `version`
- `[dependencies]` section parsed but not yet utilized (future: external packages)
- `get_package_manifest()` finds and parses Saw.toml walking up from source file

**init.saw facade support:**
- `get_facade_info()` parses init.saw to extract export declarations
- `ExportInfo` captures source path, export name, and glob flag
- Export statements restricted to init.saw files (error otherwise)

**Export syntax supported:**
| Syntax | Description |
|--------|-------------|
| `export path.to.Symbol` | Export symbol at its original name |
| `export path.to.Symbol as Name` | Export symbol with renamed alias |
| `export path.to.*` | Export all public symbols (glob) |

**Tests added:**
- `export_outside_init_error.saw` - Verifies export outside init.saw produces error
- Test package in `examples/modules/test_package/` with Saw.toml and init.saw

**Note:** Per-module type checking (5.0) was deferred. The Phase 4.5 approach of per-module namespace resolution is working well and the full per-module type checking refactor can be done as a future optimization if needed.

**Total tests:** 153

---

## Files to Modify

| File | Changes |
|------|---------|
| `sawc/lexer.py` | Add MODULE, IMPORT, PUBLIC, PACKAGE, PARENT tokens |
| `sawc/ast_nodes.py` | Add Visibility enum, ImportDecl, ModuleDecl; update Program |
| `sawc/parser.py` | Add parse_import(), parse_module_decl(), _parse_visibility() |
| `sawc/typechecker.py` | Add qualified symbol tables, check_modules(), visibility checks |
| `sawc/codegen.py` | Add name mangling for modules (`saw_std_io_File_open`) |
| `sawc/sawc.py` | Integrate ModuleResolver, update pipeline |
| **NEW** `sawc/module_resolver.py` | Module discovery and dependency ordering |

---

## Standard Library Integration

Current `std/*.saw` files need no changes initially. They're loaded by `load_builtins()` and merged as before.

Future: Restructure to proper module hierarchy with init.saw facades:
```
sawc/std/
  init.saw          # export io, export collections, etc.
  io/
    init.saw        # export File, export Read, etc.
    file.saw
  collections/
    init.saw        # export Vector, export Map, etc.
    vector.saw
    map.saw
```

---

## Backward Compatibility

Programs without `import` or `module` use existing compilation path:
1. Load builtins + std/*.saw
2. Merge into single Program
3. Type check merged AST
4. Generate code

This ensures all existing tests pass unchanged.

---

## Test Strategy

Phase 1:
- `import std.vector` → use Vector
- Import non-existent module → error

Phase 2:
- `import std.io.File` → use File directly
- `import std.io.{File, Directory}` → both available
- `import std.io as io_module` → access as io_module.File

Phase 3:
- Access private symbol → error
- Access public symbol → works

Phase 4:
- `module parser` creates sub-module
- `import package.parser` works
- Circular import → clear error message

---

## Implementation Order

1. **lexer.py**: Add 5 new tokens (~10 lines)
2. **ast_nodes.py**: Add Visibility, ImportDecl, ModuleDecl, update Program (~50 lines)
3. **parser.py**: Add import/module parsing (~100 lines)
4. **module_resolver.py**: Create new file for module discovery (~200 lines)
5. **sawc.py**: Add module-aware compilation path (~50 lines)
6. **typechecker.py**: Add qualified symbols and check_modules (~300 lines)
7. **codegen.py**: Add name mangling (~50 lines)

Total: ~760 lines of new code, significant refactoring of type checker

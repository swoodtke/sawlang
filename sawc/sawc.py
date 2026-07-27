#!/usr/bin/env python3
"""
Saw Language Compiler
A simple compiler for the Saw programming language.

Usage:
    sawc <input.saw> [-o output]

This compiles a .saw file to a native executable.
"""

import argparse
import subprocess
import sys
import os
import tempfile

from lexer import Lexer
from parser import Parser
from codegen import CodeGenerator
from errors import ErrorReporter
from typechecker import TypeChecker
from module_resolver import ModuleResolver


def parse_source(source: str, source_path: str, verbose: bool = False):
    """Parse a Saw source file and return the AST."""
    # Lexical analysis
    try:
        lexer = Lexer(source)
        tokens = lexer.tokenize()
    except SyntaxError as e:
        print(f"\033[1;31merror\033[0m: {e}", file=sys.stderr)
        sys.exit(1)

    # Parsing
    try:
        parser = Parser(tokens, source_file=source_path)
        return parser.parse()
    except SyntaxError as e:
        print(f"\033[1;31merror\033[0m: {e}", file=sys.stderr)
        sys.exit(1)


def load_builtins(verbose: bool = False):
    """Load and parse the builtin.saw file and all std/*.saw files."""
    from ast_nodes import Program

    sawc_dir = os.path.dirname(__file__)
    combined_ast = None

    # Load builtin.saw first (core traits)
    builtin_path = os.path.join(sawc_dir, 'builtin.saw')
    if os.path.exists(builtin_path):
        with open(builtin_path, 'r') as f:
            builtin_source = f.read()
        if verbose:
            print("  Loading builtins...")
        combined_ast = parse_source(builtin_source, builtin_path, verbose)

    # Load all files from std/ directory
    std_dir = os.path.join(sawc_dir, 'std')
    if os.path.isdir(std_dir):
        std_files = sorted([f for f in os.listdir(std_dir) if f.endswith('.saw')])
        for filename in std_files:
            filepath = os.path.join(std_dir, filename)
            with open(filepath, 'r') as f:
                source = f.read()
            if verbose:
                print(f"  Loading std/{filename}...")
            file_ast = parse_source(source, filepath, verbose)
            if combined_ast is None:
                combined_ast = file_ast
            else:
                combined_ast = Program(
                    structs=combined_ast.structs + file_ast.structs,
                    functions=combined_ast.functions + file_ast.functions,
                    extensions=combined_ast.extensions + file_ast.extensions,
                    enums=combined_ast.enums + file_ast.enums,
                    traits=combined_ast.traits + file_ast.traits,
                    type_definitions=combined_ast.type_definitions + file_ast.type_definitions,
                    extern_blocks=combined_ast.extern_blocks + file_ast.extern_blocks,
                    line=combined_ast.line,
                    column=combined_ast.column
                )

    return combined_ast


def merge_programs(builtin_ast, user_ast):
    """Merge builtin definitions with user program."""
    if builtin_ast is None:
        return user_ast

    from ast_nodes import Program

    return Program(
        structs=builtin_ast.structs + user_ast.structs,
        functions=builtin_ast.functions + user_ast.functions,
        extensions=builtin_ast.extensions + user_ast.extensions,
        enums=builtin_ast.enums + user_ast.enums,
        traits=builtin_ast.traits + user_ast.traits,
        type_definitions=builtin_ast.type_definitions + user_ast.type_definitions,
        extern_blocks=builtin_ast.extern_blocks + user_ast.extern_blocks,
        # Preserve user imports, module declarations, and exports (builtins don't have these)
        imports=getattr(user_ast, 'imports', []),
        module_decls=getattr(user_ast, 'module_decls', []),
        exports=getattr(user_ast, 'exports', []),
        source_path=getattr(user_ast, 'source_path', None),
        module_path=getattr(user_ast, 'module_path', None),
        line=user_ast.line,
        column=user_ast.column
    )


def uses_modules(ast) -> bool:
    """Check if the program uses the module system (has imports or module declarations)."""
    return bool(getattr(ast, 'imports', []) or getattr(ast, 'module_decls', []))


def topological_sort_modules(module_map):
    """
    Topologically sort modules by their dependencies.

    Modules are sorted so that dependencies come before dependents.
    This ensures that when type-checking a module, all its imports
    have already been type-checked.

    Args:
        module_map: Dict of module_path_tuple -> AST

    Returns:
        List of module_path_tuple in dependency order
    """
    # Build dependency graph
    # For each module, find what it imports and declares
    dependencies = {}  # module_path -> set of module_paths it depends on
    for mod_path, mod_ast in module_map.items():
        deps = set()
        for imp in getattr(mod_ast, 'imports', []):
            imp_path = tuple(imp.path)
            # Handle package/parent prefixes
            if imp_path and imp_path[0] == 'package':
                imp_path = imp_path[1:]
            elif imp_path and imp_path[0] == 'parent':
                imp_path = imp_path[1:]
            if imp_path in module_map:
                deps.add(imp_path)
        # Also add external module declarations as dependencies
        # e.g., `public module lib` means this module depends on lib
        for mod_decl in getattr(mod_ast, 'module_decls', []):
            if not mod_decl.is_inline:
                decl_path = (mod_decl.name,)
                if decl_path in module_map:
                    deps.add(decl_path)
        dependencies[mod_path] = deps

    # Kahn's algorithm for topological sort
    # Count incoming edges for each node
    in_degree = {mod: 0 for mod in module_map}
    for mod, deps in dependencies.items():
        for dep in deps:
            if dep in in_degree:
                in_degree[mod] += 1

    # Start with nodes that have no dependencies
    queue = [mod for mod, degree in in_degree.items() if degree == 0]
    result = []

    while queue:
        mod = queue.pop(0)
        result.append(mod)

        # For each module that depends on this one, reduce its in-degree
        for other_mod, deps in dependencies.items():
            if mod in deps:
                in_degree[other_mod] -= 1
                if in_degree[other_mod] == 0:
                    queue.append(other_mod)

    # Check for cycles
    if len(result) != len(module_map):
        # There's a cycle - just return in arbitrary order
        # The type checker will handle any errors
        return list(module_map.keys())

    return result


def compile_with_modules(source_path: str, output_path: str, entry_ast, entry_source: str, verbose: bool = False, object_only: bool = False, optimize: bool = True):
    """
    Compile a program that uses the module system.

    This implements Phase 2 multi-module compilation:
    1. Resolve all module imports to their source files
    2. Parse imported modules
    3. Build module map for qualified access
    4. Merge all modules with builtins for code generation
    5. Type check with module-aware symbol resolution
    6. Generate code
    7. Link to executable (unless object_only=True)

    Args:
        object_only: If True, compile to .o without linking (no main() required)
    """
    from module_resolver import ModuleInfo
    from ast_nodes import Program

    if verbose:
        print("  Resolving module dependencies...")

    # Create resolver with search paths
    source_dir = os.path.dirname(os.path.abspath(source_path))
    resolver = ModuleResolver([source_dir])

    # Resolve all imports and collect module ASTs
    # module_map: module_path_tuple -> AST (for qualified access)
    module_map = {}
    module_sources = {}  # source_path -> source (for error reporting)
    resolved_modules = set()
    pending_imports = list(getattr(entry_ast, 'imports', []))

    while pending_imports:
        imp = pending_imports.pop(0)
        module_path = tuple(imp.path)

        # Skip package/parent prefix for resolution
        if imp.path and imp.path[0] in ('package', 'parent'):
            resolved_path = resolver.resolve_import_path(imp.path, [])
            module_path = tuple(resolved_path)

        if module_path in resolved_modules:
            continue

        # Try to resolve the module
        mod_info = resolver.resolve_module(list(module_path), source_path)
        if mod_info:
            # Load and parse the module
            resolver.load_module_source(mod_info)
            mod_ast = parse_source(mod_info.source, mod_info.source_path, verbose)
            # Track source for error reporting
            module_sources[mod_info.source_path] = mod_info.source

            if verbose:
                print(f"    Resolved: {'.'.join(module_path)} -> {mod_info.source_path}")

            module_map[module_path] = mod_ast
            resolved_modules.add(module_path)

            # Add this module's imports to pending
            for sub_imp in getattr(mod_ast, 'imports', []):
                pending_imports.append(sub_imp)

            # Also process external module declarations from this imported module
            # This enables re-exporting: if mod.saw has `public module lib`,
            # then lib.saw needs to be loaded
            mod_source_dir = os.path.dirname(mod_info.source_path)
            for mod_decl in getattr(mod_ast, 'module_decls', []):
                if not mod_decl.is_inline:
                    simple_path = (mod_decl.name,)
                    if simple_path not in resolved_modules:
                        # Look for the module file relative to the imported module
                        sub_mod_file = os.path.join(mod_source_dir, f"{mod_decl.name}.saw")
                        sub_mod_dir_file = os.path.join(mod_source_dir, mod_decl.name, "module.saw")

                        if os.path.isfile(sub_mod_file):
                            with open(sub_mod_file, 'r') as f:
                                sub_mod_source = f.read()
                            sub_mod_ast = parse_source(sub_mod_source, sub_mod_file, verbose)
                            module_sources[sub_mod_file] = sub_mod_source
                            # Register with simple path only (avoids duplicate merging)
                            module_map[(mod_decl.name,)] = sub_mod_ast
                            resolved_modules.add((mod_decl.name,))
                            if verbose:
                                print(f"    Module decl: {mod_decl.name} -> {sub_mod_file}")

                            # Recursively process imports from this module
                            for sub_imp in getattr(sub_mod_ast, 'imports', []):
                                pending_imports.append(sub_imp)
                        elif os.path.isfile(sub_mod_dir_file):
                            with open(sub_mod_dir_file, 'r') as f:
                                sub_mod_source = f.read()
                            sub_mod_ast = parse_source(sub_mod_source, sub_mod_dir_file, verbose)
                            module_sources[sub_mod_dir_file] = sub_mod_source
                            module_map[(mod_decl.name,)] = sub_mod_ast
                            resolved_modules.add((mod_decl.name,))
                            if verbose:
                                print(f"    Module decl: {mod_decl.name} -> {sub_mod_dir_file}")

                            for sub_imp in getattr(sub_mod_ast, 'imports', []):
                                pending_imports.append(sub_imp)
                        else:
                            print(f"\033[1;31merror\033[0m: module `{mod_decl.name}` not found (declared in {mod_info.source_path})", file=sys.stderr)
                            sys.exit(1)
        else:
            # Module not found - report error
            print(f"\033[1;31merror\033[0m: module `{'.'.join(module_path)}` not found", file=sys.stderr)
            sys.exit(1)

    if verbose:
        print(f"    Resolved {len(module_map)} imported module(s)")

    # Process module declarations (Phase 4)
    # module_decls can be external (module foo) or inline (module foo { ... })
    inline_modules = {}  # name -> Program (for inline modules)
    for mod_decl in getattr(entry_ast, 'module_decls', []):
        if mod_decl.is_inline:
            # Inline module - store body for later processing
            inline_modules[mod_decl.name] = mod_decl.body
            if verbose:
                print(f"    Inline module: {mod_decl.name}")
        else:
            # External module declaration - load from file
            # Look for name.saw or name/module.saw in the source directory
            mod_path = (mod_decl.name,)

            if mod_path not in resolved_modules:
                # Look in source directory for the module file
                source_dir = os.path.dirname(os.path.abspath(source_path))
                mod_file = os.path.join(source_dir, f"{mod_decl.name}.saw")
                mod_dir_file = os.path.join(source_dir, mod_decl.name, "module.saw")

                if os.path.isfile(mod_file):
                    with open(mod_file, 'r') as f:
                        mod_source = f.read()
                    mod_ast = parse_source(mod_source, mod_file, verbose)
                    module_map[mod_path] = mod_ast
                    resolved_modules.add(mod_path)
                    if verbose:
                        print(f"    Module: {mod_decl.name} -> {mod_file}")

                    # Also process any imports from this module
                    for sub_imp in getattr(mod_ast, 'imports', []):
                        pending_imports.append(sub_imp)
                elif os.path.isfile(mod_dir_file):
                    with open(mod_dir_file, 'r') as f:
                        mod_source = f.read()
                    mod_ast = parse_source(mod_source, mod_dir_file, verbose)
                    module_map[mod_path] = mod_ast
                    resolved_modules.add(mod_path)
                    if verbose:
                        print(f"    Module: {mod_decl.name} -> {mod_dir_file}")

                    # Also process any imports from this module
                    for sub_imp in getattr(mod_ast, 'imports', []):
                        pending_imports.append(sub_imp)
                else:
                    print(f"\033[1;31merror\033[0m: module `{mod_decl.name}` not found at {mod_file} or {mod_dir_file}", file=sys.stderr)
                    sys.exit(1)

    # Load builtins
    builtin_ast = load_builtins(verbose)

    # Helper to recursively collect all inline module bodies from an AST
    def collect_inline_module_bodies(ast):
        """Recursively collect all inline module bodies from an AST."""
        bodies = []
        for mod_decl in getattr(ast, 'module_decls', []):
            if mod_decl.is_inline and mod_decl.body:
                bodies.append(mod_decl.body)
                # Recursively collect from nested inline modules
                bodies.extend(collect_inline_module_bodies(mod_decl.body))
        return bodies

    # Build merged AST for code generation (still needed for codegen)
    # Start with builtins
    merged_ast = builtin_ast

    # Merge ALL imported modules (needed for codegen - symbols must exist)
    for mod_ast in module_map.values():
        merged_ast = merge_programs(merged_ast, mod_ast)
        # Also merge inline module bodies from imported modules
        for inline_body in collect_inline_module_bodies(mod_ast):
            merged_ast = merge_programs(merged_ast, inline_body)

    # Merge inline modules from entry file (their symbols need to exist for codegen)
    for mod_name, mod_body in inline_modules.items():
        merged_ast = merge_programs(merged_ast, mod_body)
        # Also recursively merge any nested inline modules
        for inline_body in collect_inline_module_bodies(mod_body):
            merged_ast = merge_programs(merged_ast, inline_body)

    # Add entry module
    merged_ast = merge_programs(merged_ast, entry_ast)

    if verbose:
        print(f"    Merged {len(merged_ast.functions)} functions total")

    # =========================================================================
    # Phase 5.0: Per-Module Type Checking
    # =========================================================================
    # Type-check each module separately with its own namespace, then merge
    # namespaces for codegen. This ensures proper import scoping.

    if verbose:
        print("  Type checking (per-module)...")

    reporter = ErrorReporter(entry_source, source_path)
    # Add imported module sources for proper error context
    for mod_path, mod_source in module_sources.items():
        reporter.add_source(mod_path, mod_source)
    typechecker = TypeChecker(reporter)

    # First, type-check the builtins using the legacy method
    # This sets resolved_type on expressions in the builtin AST
    if verbose:
        print("    Type-checking builtins...")

    # Create a temporary error reporter for builtins to avoid polluting user errors
    builtin_reporter = ErrorReporter("", "builtins")
    builtin_typechecker = TypeChecker(builtin_reporter)

    # Type-check builtins (this populates the namespace and sets resolved_type)
    # Use a copy of builtin_ast for checking (we don't want main check errors)
    builtin_typechecker.namespace.allow_all_access = True  # Allow all access for builtins
    for type_def in builtin_ast.type_definitions:
        builtin_typechecker._register_type_definition(type_def)
    for struct in builtin_ast.structs:
        builtin_typechecker._register_struct(struct)
    for enum in builtin_ast.enums:
        builtin_typechecker._register_enum(enum)
    for trait in builtin_ast.traits:
        builtin_typechecker._register_trait(trait)
    for extension in builtin_ast.extensions:
        builtin_typechecker._register_extension(extension)
    for extern_block in builtin_ast.extern_blocks:
        for extern_func in extern_block.functions:
            builtin_typechecker._register_extern_function(extern_func)
    for func in builtin_ast.functions:
        builtin_typechecker._register_function(func)

    # Type-check the function and method bodies (sets resolved_type on expressions)
    for func in builtin_ast.functions:
        builtin_typechecker._check_function(func)
    for extension in builtin_ast.extensions:
        builtin_typechecker._check_extension(extension)

    # Now create the builtin namespace for the per-module type checking
    builtin_ns = builtin_typechecker.namespace

    # Make all builtin symbols directly accessible to modules
    # This allows modules to use Vector, Map, String, etc. without explicit imports
    for name in builtin_ns.structs:
        builtin_ns.make_accessible(name)
    for name in builtin_ns.enums:
        builtin_ns.make_accessible(name)
    for name in builtin_ns.functions:
        builtin_ns.make_accessible(name)
    for name in builtin_ns.traits:
        builtin_ns.make_accessible(name)
    for name in builtin_ns.type_aliases:
        builtin_ns.make_accessible(name)

    # All type information is now namespace-only
    # (structs, traits, functions, enums, type_aliases, conformances, type_assignments)

    # Topologically sort modules by dependencies
    ordered_modules = topological_sort_modules(module_map)

    if verbose:
        print(f"    Type-checking {len(ordered_modules)} module(s) in dependency order")

    # Type-check each module in dependency order
    # checked_modules: module_path -> (ast, namespace)
    checked_modules = {}

    for mod_path in ordered_modules:
        mod_ast = module_map[mod_path]
        if verbose:
            print(f"      Checking module: {'.'.join(mod_path)}")

        mod_ns = typechecker.check_module(
            mod_ast,
            mod_path,
            checked_modules,
            builtin_ns,
            parent_namespace=None,
            is_entry=False
        )

        if mod_ns is None:
            reporter.print_all()
            sys.exit(1)

        checked_modules[mod_path] = (mod_ast, mod_ns)

    # Type-check external module declarations
    for mod_decl in getattr(entry_ast, 'module_decls', []):
        if not mod_decl.is_inline:
            mod_path = (mod_decl.name,)
            if mod_path in module_map and mod_path not in checked_modules:
                mod_ast = module_map[mod_path]
                if verbose:
                    print(f"      Checking module: {mod_decl.name}")

                mod_ns = typechecker.check_module(
                    mod_ast,
                    mod_path,
                    checked_modules,
                    builtin_ns,
                    parent_namespace=None,
                    is_entry=False
                )

                if mod_ns is None:
                    reporter.print_all()
                    sys.exit(1)

                checked_modules[mod_path] = (mod_ast, mod_ns)

    # Type-check the entry module
    if verbose:
        print("      Checking entry module")

    entry_ns = typechecker.check_module(
        entry_ast,
        (),  # Entry module has empty path
        checked_modules,
        builtin_ns,
        parent_namespace=None,
        is_entry=not object_only  # Only require main() for executables
    )

    if entry_ns is None:
        reporter.print_all()
        sys.exit(1)

    if verbose:
        print("    Type check passed")

    # Merge all namespaces for codegen
    # Start with builtin namespace, then merge all module namespaces
    from namespace import Namespace
    merged_ns = Namespace()
    merged_ns.merge_into(builtin_ns)

    for mod_path, (mod_ast, mod_ns) in checked_modules.items():
        merged_ns.merge_into(mod_ns)

    merged_ns.merge_into(entry_ns)

    # Set this as the typechecker's namespace for compatibility
    typechecker.namespace = merged_ns

    # Code generation
    if verbose:
        print("  Generating LLVM IR...")
    codegen = CodeGenerator(typechecker.namespace)
    llvm_ir = codegen.generate(merged_ast)

    if verbose:
        print("  Generated LLVM IR")

    # Write LLVM IR to temp file (for debugging)
    ir_path = output_path + ".ll"
    with open(ir_path, 'w') as f:
        f.write(llvm_ir)

    if verbose:
        print(f"  Wrote IR to {ir_path}")

    # Compile to object file
    if verbose:
        print("  Compiling to object code...")

    if object_only:
        # Output directly to the specified path (should end in .o)
        obj_path = output_path if output_path.endswith('.o') else output_path + '.o'
        codegen.compile_to_object(obj_path, optimize=optimize)

        if verbose:
            print(f"  Output: {obj_path}")
        print(f"Compiled {source_path} -> {obj_path}")
    else:
        # Compile to temp object file, then link
        obj_path = output_path + ".o"
        codegen.compile_to_object(obj_path, optimize=optimize)

        # Link with system linker
        if verbose:
            print("  Linking...")

        link_cmd = ["clang", obj_path, "-o", output_path]

        try:
            result = subprocess.run(link_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"Linking failed: {result.stderr}", file=sys.stderr)
                sys.exit(1)
        except FileNotFoundError:
            print("Error: clang not found. Please install LLVM/clang.", file=sys.stderr)
            sys.exit(1)

        # Clean up object file
        os.remove(obj_path)

        if verbose:
            print(f"  Output: {output_path}")

        print(f"Compiled {source_path} -> {output_path}")


def compile_saw(source_path: str, output_path: str, verbose: bool = False, object_only: bool = False, optimize: bool = True):
    """Compile a Saw source file to an executable or object file.

    Args:
        source_path: Path to the .saw source file
        output_path: Path for output (executable or .o file)
        verbose: Print verbose progress messages
        object_only: If True, compile to .o without linking (no main() required)
        optimize: If True (default), run the O1 optimization pipeline; -O0 disables it
    """

    # Read source file
    with open(source_path, 'r') as f:
        source = f.read()

    if verbose:
        print(f"Compiling {source_path}...")

    # Parse user source first to check for modules
    if verbose:
        print("  Parsing...")
    user_ast = parse_source(source, source_path, verbose)
    user_ast.source_path = os.path.abspath(source_path)

    # Check if this program uses the module system
    if uses_modules(user_ast):
        if verbose:
            print("  Module system detected:")
            for imp in user_ast.imports:
                print(f"    import {'.'.join(imp.path)}")
            for mod in user_ast.module_decls:
                print(f"    module {mod.name}")

        # Use multi-module compilation path
        return compile_with_modules(source_path, output_path, user_ast, source, verbose, object_only, optimize)

    # Legacy single-file compilation path
    # Load builtins
    builtin_ast = load_builtins(verbose)

    # Merge builtins with user program
    ast = merge_programs(builtin_ast, user_ast)

    if verbose:
        print(f"    Parsed {len(ast.functions)} functions")

    # Type checking
    if verbose:
        print("  Type checking...")
    reporter = ErrorReporter(source, source_path)
    typechecker = TypeChecker(reporter)
    if not typechecker.check(ast, require_main=not object_only):
        reporter.print_all()
        sys.exit(1)

    if verbose:
        print("    Type check passed")

    # Code generation
    if verbose:
        print("  Generating LLVM IR...")
    codegen = CodeGenerator(typechecker.namespace)
    llvm_ir = codegen.generate(ast)

    if verbose:
        print("  Generated LLVM IR")

    # Write LLVM IR to temp file (for debugging)
    ir_path = output_path + ".ll"
    with open(ir_path, 'w') as f:
        f.write(llvm_ir)

    if verbose:
        print(f"  Wrote IR to {ir_path}")

    # Compile to object file
    if verbose:
        print("  Compiling to object code...")

    if object_only:
        # Output directly to the specified path (should end in .o)
        obj_path = output_path if output_path.endswith('.o') else output_path + '.o'
        codegen.compile_to_object(obj_path, optimize=optimize)

        if verbose:
            print(f"  Output: {obj_path}")
        print(f"Compiled {source_path} -> {obj_path}")
    else:
        # Compile to temp object file, then link
        obj_path = output_path + ".o"
        codegen.compile_to_object(obj_path, optimize=optimize)

        # Link with system linker
        if verbose:
            print("  Linking...")

        # Use clang as the linker (handles libc linking automatically)
        link_cmd = ["clang", obj_path, "-o", output_path]

        try:
            result = subprocess.run(link_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"Linking failed: {result.stderr}", file=sys.stderr)
                sys.exit(1)
        except FileNotFoundError:
            print("Error: clang not found. Please install LLVM/clang.", file=sys.stderr)
            sys.exit(1)

        # Clean up object file
        os.remove(obj_path)

        if verbose:
            print(f"  Output: {output_path}")

        print(f"Compiled {source_path} -> {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Saw Language Compiler",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    sawc hello.saw              Compile hello.saw to ./hello
    sawc hello.saw -o myprogram Compile to ./myprogram
    sawc hello.saw -v           Verbose output
        """
    )

    parser.add_argument("input", help="Input .saw file")
    parser.add_argument("-o", "--output", help="Output executable name")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("-c", action="store_true", help="Compile to object file (.o) without linking, no main() required")
    parser.add_argument("--emit-ir", action="store_true", help="Only emit LLVM IR, don't compile")
    parser.add_argument("--emit-ast", action="store_true", help="Dump typed AST for debugging")
    parser.add_argument("-O0", dest="no_optimize", action="store_true",
                        help="Disable optimization passes (emit raw codegen output for debugging)")

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: File not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        # Use input filename without extension, place in .build/ directory
        basename = os.path.basename(args.input)
        name_without_ext = os.path.splitext(basename)[0]

        # Ensure .build/ directory exists
        build_dir = ".build"
        os.makedirs(build_dir, exist_ok=True)

        output_path = os.path.join(build_dir, name_without_ext)

    if args.emit_ast:
        # Dump typed AST
        from ast_dump import dump_ast

        with open(args.input, 'r') as f:
            source = f.read()

        # Load builtins
        builtin_ast = load_builtins(args.verbose)

        try:
            lexer = Lexer(source)
            tokens = lexer.tokenize()
            parser_obj = Parser(tokens)
            user_ast = parser_obj.parse()
        except SyntaxError as e:
            print(f"\033[1;31merror\033[0m: {e}", file=sys.stderr)
            sys.exit(1)

        # Merge builtins with user program
        ast = merge_programs(builtin_ast, user_ast)

        # Type check (this annotates None types, etc.)
        reporter = ErrorReporter(source, args.input)
        typechecker = TypeChecker(reporter)
        if not typechecker.check(ast):
            reporter.print_all()
            sys.exit(1)

        # Dump AST
        ast_output = dump_ast(ast)
        print(ast_output)

    elif args.emit_ir:
        # Only emit IR
        with open(args.input, 'r') as f:
            source = f.read()

        try:
            lexer = Lexer(source)
            tokens = lexer.tokenize()
            parser_obj = Parser(tokens)
            ast = parser_obj.parse()
        except SyntaxError as e:
            print(f"\033[1;31merror\033[0m: {e}", file=sys.stderr)
            sys.exit(1)

        # Type check
        reporter = ErrorReporter(source, args.input)
        typechecker = TypeChecker(reporter)
        if not typechecker.check(ast):
            reporter.print_all()
            sys.exit(1)

        codegen = CodeGenerator(typechecker.namespace)
        codegen.generate(ast)
        llvm_ir = codegen.emit_ir(optimize=not args.no_optimize)

        ir_output = output_path + ".ll"
        with open(ir_output, 'w') as f:
            f.write(llvm_ir)
        print(f"Emitted IR to {ir_output}")
    else:
        # If -c flag, ensure output ends with .o
        if args.c and not output_path.endswith('.o'):
            output_path = output_path + '.o'
        compile_saw(args.input, output_path, verbose=args.verbose, object_only=args.c, optimize=not args.no_optimize)


if __name__ == "__main__":
    main()

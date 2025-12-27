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
        parser = Parser(tokens)
        return parser.parse()
    except SyntaxError as e:
        print(f"\033[1;31merror\033[0m: {e}", file=sys.stderr)
        sys.exit(1)


def load_builtins(verbose: bool = False):
    """Load and parse the builtin.saw file and all std/*.saw files."""
    from ast_nodes import Program

    sawc_dir = os.path.dirname(__file__)
    combined_ast = None

    # Load builtin.saw first (core interfaces)
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
                    interfaces=combined_ast.interfaces + file_ast.interfaces,
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
        interfaces=builtin_ast.interfaces + user_ast.interfaces,
        type_definitions=builtin_ast.type_definitions + user_ast.type_definitions,
        extern_blocks=builtin_ast.extern_blocks + user_ast.extern_blocks,
        # Preserve user imports and module declarations (builtins don't have these)
        imports=getattr(user_ast, 'imports', []),
        module_decls=getattr(user_ast, 'module_decls', []),
        source_path=getattr(user_ast, 'source_path', None),
        module_path=getattr(user_ast, 'module_path', None),
        line=user_ast.line,
        column=user_ast.column
    )


def uses_modules(ast) -> bool:
    """Check if the program uses the module system (has imports or module declarations)."""
    return bool(getattr(ast, 'imports', []) or getattr(ast, 'module_decls', []))


def compile_with_modules(source_path: str, output_path: str, entry_ast, entry_source: str, verbose: bool = False):
    """
    Compile a program that uses the module system.

    This implements Phase 2 multi-module compilation:
    1. Resolve all module imports to their source files
    2. Parse imported modules
    3. Build module map for qualified access
    4. Merge all modules with builtins for code generation
    5. Type check with module-aware symbol resolution
    6. Generate code
    7. Link to executable
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

            if verbose:
                print(f"    Resolved: {'.'.join(module_path)} -> {mod_info.source_path}")

            module_map[module_path] = mod_ast
            resolved_modules.add(module_path)

            # Add this module's imports to pending
            for sub_imp in getattr(mod_ast, 'imports', []):
                pending_imports.append(sub_imp)
        else:
            # Module not found - report error
            print(f"\033[1;31merror\033[0m: module `{'.'.join(module_path)}` not found", file=sys.stderr)
            sys.exit(1)

    if verbose:
        print(f"    Resolved {len(module_map)} imported module(s)")

    # Load builtins
    builtin_ast = load_builtins(verbose)

    # Separate imports by type:
    # - Module imports (import foo) -> only accessible via qualified name (foo.X)
    # - Glob imports (import foo.*) -> all symbols directly accessible
    # - Symbol imports (import foo.{A,B}) -> specific symbols directly accessible
    module_imports = []      # import foo.bar
    glob_imports = []        # import foo.*
    symbol_imports = []      # import foo.{A, B}

    for imp in entry_ast.imports:
        if imp.is_glob:
            glob_imports.append(imp)
        elif imp.symbols:
            symbol_imports.append(imp)
        else:
            module_imports.append(imp)

    # Build merged AST for code generation and type checking
    # Start with builtins
    merged_ast = builtin_ast

    # Merge ALL imported modules (needed for codegen - symbols must exist)
    for mod_ast in module_map.values():
        merged_ast = merge_programs(merged_ast, mod_ast)

    # Add entry module
    merged_ast = merge_programs(merged_ast, entry_ast)

    if verbose:
        print(f"    Merged {len(merged_ast.functions)} functions total")

    # Type check
    if verbose:
        print("  Type checking...")
    reporter = ErrorReporter(entry_source, source_path)
    typechecker = TypeChecker(reporter)

    # Enable import-based accessibility checking
    typechecker.namespace.enable_import_checking()

    # Mark builtins as directly accessible
    for struct in builtin_ast.structs:
        typechecker.namespace.make_accessible(struct.name)
    for enum in builtin_ast.enums:
        typechecker.namespace.make_accessible(enum.name)
    for func in builtin_ast.functions:
        typechecker.namespace.make_accessible(func.name)
    for iface in builtin_ast.interfaces:
        typechecker.namespace.make_accessible(iface.name)
    for type_def in builtin_ast.type_definitions:
        typechecker.namespace.make_accessible(type_def.name)
    for extern_block in builtin_ast.extern_blocks:
        for extern_func in extern_block.functions:
            typechecker.namespace.make_accessible(extern_func.name)

    # Mark entry module's own symbols as accessible
    for struct in entry_ast.structs:
        typechecker.namespace.make_accessible(struct.name)
    for enum in entry_ast.enums:
        typechecker.namespace.make_accessible(enum.name)
    for func in entry_ast.functions:
        typechecker.namespace.make_accessible(func.name)
    for iface in entry_ast.interfaces:
        typechecker.namespace.make_accessible(iface.name)
    for type_def in entry_ast.type_definitions:
        typechecker.namespace.make_accessible(type_def.name)

    # Process imports to set up accessibility
    for imp in module_imports:
        # import foo.bar -> register module, accessible as 'bar' (qualified only)
        mod_path = tuple(imp.path)
        if mod_path in module_map:
            alias = imp.alias or imp.path[-1]
            typechecker.namespace.register_module_from_ast(
                alias, module_map[mod_path], list(mod_path)
            )

    for imp in glob_imports:
        # import foo.* -> all symbols from module are directly accessible
        mod_path = tuple(imp.path[:-1]) if imp.path[-1] == '*' else tuple(imp.path)
        if mod_path in module_map:
            mod_ast = module_map[mod_path]
            for struct in mod_ast.structs:
                typechecker.namespace.make_accessible(struct.name)
            for enum in mod_ast.enums:
                typechecker.namespace.make_accessible(enum.name)
            for func in mod_ast.functions:
                typechecker.namespace.make_accessible(func.name)
            for iface in mod_ast.interfaces:
                typechecker.namespace.make_accessible(iface.name)

    for imp in symbol_imports:
        # import foo.{A, B} -> only A and B are directly accessible
        mod_path = tuple(imp.path)
        if mod_path in module_map:
            for sym_name in imp.symbols:
                typechecker.namespace.make_accessible(sym_name)

    if not typechecker.check(merged_ast):
        reporter.print_all()
        sys.exit(1)

    if verbose:
        print("    Type check passed")

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
    obj_path = output_path + ".o"
    codegen.compile_to_object(obj_path)

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


def compile_saw(source_path: str, output_path: str, verbose: bool = False):
    """Compile a Saw source file to an executable."""

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
        return compile_with_modules(source_path, output_path, user_ast, source, verbose)

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
    if not typechecker.check(ast):
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
    obj_path = output_path + ".o"
    codegen.compile_to_object(obj_path)

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
    parser.add_argument("--emit-ir", action="store_true", help="Only emit LLVM IR, don't compile")
    parser.add_argument("--emit-ast", action="store_true", help="Dump typed AST for debugging")

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
        llvm_ir = codegen.generate(ast)

        ir_output = output_path + ".ll"
        with open(ir_output, 'w') as f:
            f.write(llvm_ir)
        print(f"Emitted IR to {ir_output}")
    else:
        compile_saw(args.input, output_path, verbose=args.verbose)


if __name__ == "__main__":
    main()

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


def compile_saw(source_path: str, output_path: str, verbose: bool = False):
    """Compile a Saw source file to an executable."""

    # Read source file
    with open(source_path, 'r') as f:
        source = f.read()

    if verbose:
        print(f"Compiling {source_path}...")

    # Lexical analysis
    if verbose:
        print("  Lexing...")
    try:
        lexer = Lexer(source)
        tokens = lexer.tokenize()
    except SyntaxError as e:
        print(f"\033[1;31merror\033[0m: {e}", file=sys.stderr)
        sys.exit(1)

    if verbose:
        print(f"    Generated {len(tokens)} tokens")

    # Parsing
    if verbose:
        print("  Parsing...")
    try:
        parser = Parser(tokens)
        ast = parser.parse()
    except SyntaxError as e:
        print(f"\033[1;31merror\033[0m: {e}", file=sys.stderr)
        sys.exit(1)

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
    codegen = CodeGenerator()
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

    if args.emit_ir:
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

        codegen = CodeGenerator()
        llvm_ir = codegen.generate(ast)

        ir_output = output_path + ".ll"
        with open(ir_output, 'w') as f:
            f.write(llvm_ir)
        print(f"Emitted IR to {ir_output}")
    else:
        compile_saw(args.input, output_path, verbose=args.verbose)


if __name__ == "__main__":
    main()

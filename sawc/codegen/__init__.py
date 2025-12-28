"""
Saw Language Code Generator Package

This package provides the CodeGenerator class for generating LLVM IR from
the Saw AST. The implementation is split across multiple mixin modules for
better organization:

- core.py: Main CodeGenerator class, state, and orchestration
- types.py: LLVM type conversion
- resources.py: Cleanup, deinit, copy behavior
- generics.py: Monomorphization of generic types and functions
- closures.py: Closure generation
- optionals.py: Optional handling (None, !, ??, ?.)
- conditionals.py: If/if-let/guard-let expressions
- loops.py: While/for loops, break/continue
- methods.py: Method and function generation
- statements.py: Statement generation
- operators.py: Binary/unary operators, cast, move
- calls.py: Function calls, method calls, enum init
- collections.py: Tuple/array literals and indexing
- structs.py: Struct initialization and member access
- match.py: Match expressions

Usage:
    from codegen import CodeGenerator
"""

from .core import CodeGenerator

__all__ = ['CodeGenerator']

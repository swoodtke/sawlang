"""
Saw Language Parser Package

This package provides the Parser class for parsing Saw source code into an AST.
The implementation is split across mixin modules:

- core.py: the Parser class, token access, doc comments, top-level declarations
- declarations.py: structs, enums, traits, extensions, functions, externs
- statements.py: blocks and statements
- expressions.py: expressions, closures, patterns
- types.py: type annotations

Usage:
    from parser import Parser
"""

from .core import Parser

__all__ = ['Parser']

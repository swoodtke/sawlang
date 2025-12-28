"""
Saw Language Parser Package

This package provides the Parser class for parsing Saw source code into an AST.
The implementation is split across multiple mixin modules for better organization:

- core.py: Main Parser class and core parsing utilities
- types.py: Type annotation parsing

Usage:
    from parser import Parser
"""

from .core import Parser

__all__ = ['Parser']

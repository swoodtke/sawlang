"""
Saw Language Type Checker Package

This package provides the TypeChecker class for type checking and semantic
analysis of Saw programs. The implementation is split across multiple mixin
modules for better organization:

- core.py: Main TypeChecker class, data classes, and orchestration
- types.py: Type resolution, compatibility, and resource trait checking

Usage:
    from typechecker import TypeChecker
"""

from .core import (
    TypeChecker,
    VariableInfo,
    FunctionInfo,
    StructInfo,
    EnumInfo,
    MethodInfo,
    TraitMethodInfo,
    TraitInfo,
    Scope
)

__all__ = [
    'TypeChecker',
    'VariableInfo',
    'FunctionInfo',
    'StructInfo',
    'EnumInfo',
    'MethodInfo',
    'TraitMethodInfo',
    'TraitInfo',
    'Scope'
]

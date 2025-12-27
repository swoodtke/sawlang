"""
Base visitor pattern for Saw AST traversal.

Provides reflection-based dispatch similar to Python's ast.NodeVisitor.
Subclasses implement visit_NodeName methods for specific node types.
"""

from typing import TypeVar, Generic, Optional

T = TypeVar('T')


class ASTVisitor(Generic[T]):
    """
    Base visitor class using reflection-based dispatch.

    Subclasses implement visit_NodeName methods for specific node types.
    For example: visit_IntLiteral, visit_BinaryOp, etc.

    The generic type T represents the return type of visit methods.
    """

    def visit(self, node) -> T:
        """Visit a node by dispatching to the appropriate visit_* method."""
        method_name = f'visit_{node.__class__.__name__}'
        visitor = getattr(self, method_name, self.generic_visit)
        return visitor(node)

    def generic_visit(self, node) -> T:
        """Called when no specific visitor method exists.

        Override this in subclasses to provide default behavior.
        """
        raise NotImplementedError(
            f"No visitor method for {node.__class__.__name__}"
        )

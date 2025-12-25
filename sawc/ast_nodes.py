"""
Saw Language AST Node Definitions
"""

from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum, auto


class TypeKind(Enum):
    INT = auto()
    FLOAT = auto()
    BOOL = auto()
    STRING = auto()
    VOID = auto()


@dataclass
class SawType:
    kind: TypeKind

    def __repr__(self):
        return self.kind.name


# Base AST Node - no default values to avoid inheritance issues
@dataclass
class ASTNode:
    pass


# Expressions
@dataclass
class Expression(ASTNode):
    pass


@dataclass
class IntLiteral(Expression):
    value: int
    line: int = 0
    column: int = 0


@dataclass
class FloatLiteral(Expression):
    value: float
    line: int = 0
    column: int = 0


@dataclass
class BoolLiteral(Expression):
    value: bool
    line: int = 0
    column: int = 0


@dataclass
class StringLiteral(Expression):
    value: str
    line: int = 0
    column: int = 0


@dataclass
class Identifier(Expression):
    name: str
    line: int = 0
    column: int = 0


@dataclass
class BinaryOp(Expression):
    op: str
    left: Expression
    right: Expression
    line: int = 0
    column: int = 0


@dataclass
class UnaryOp(Expression):
    op: str
    operand: Expression
    line: int = 0
    column: int = 0


@dataclass
class FunctionCall(Expression):
    name: str
    arguments: List[Expression]
    line: int = 0
    column: int = 0


@dataclass
class IfExpr(Expression):
    condition: Expression
    then_branch: 'Block'
    else_branch: Optional['Block'] = None
    line: int = 0
    column: int = 0


# Statements
@dataclass
class Statement(ASTNode):
    pass


@dataclass
class LetStatement(Statement):
    name: str
    type_annotation: Optional[SawType]
    value: Expression
    mutable: bool = False
    line: int = 0
    column: int = 0


@dataclass
class AssignStatement(Statement):
    name: str
    value: Expression
    line: int = 0
    column: int = 0


@dataclass
class ReturnStatement(Statement):
    value: Optional[Expression]
    line: int = 0
    column: int = 0


@dataclass
class ExpressionStatement(Statement):
    expression: Expression
    line: int = 0
    column: int = 0


@dataclass
class Block(ASTNode):
    statements: List[Statement]
    final_expr: Optional[Expression] = None
    line: int = 0
    column: int = 0


# Declarations
@dataclass
class Parameter:
    name: str
    type: SawType


@dataclass
class Function(ASTNode):
    name: str
    parameters: List[Parameter]
    return_type: SawType
    body: Block
    line: int = 0
    column: int = 0


@dataclass
class Program(ASTNode):
    functions: List[Function]
    line: int = 0
    column: int = 0

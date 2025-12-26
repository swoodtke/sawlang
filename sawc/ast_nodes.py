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
    TUPLE = auto()
    STRUCT = auto()
    OPTIONAL = auto()
    ENUM = auto()
    TYPE_PARAM = auto()  # For generic type parameters like T, U
    ARRAY = auto()       # For fixed-size arrays [T; N]
    FUNCTION = auto()    # For function types like (Int) -> Int
    SELF = auto()        # For Self type in interface methods


@dataclass
class SawType:
    kind: TypeKind
    # For tuple types, this holds the element types
    element_types: Optional[List['SawType']] = None
    # For struct types, this holds the struct name
    struct_name: Optional[str] = None
    # For optional types, this holds the inner type
    inner_type: Optional['SawType'] = None
    # For enum types, this holds the enum name
    enum_name: Optional[str] = None
    # For generic types, this holds the type arguments (e.g., Box<Int> has type_args=[Int])
    type_args: Optional[List['SawType']] = None
    # For type parameters (T, U), this holds the parameter name
    type_param_name: Optional[str] = None
    # For array types, this holds the element type and size
    array_element_type: Optional['SawType'] = None
    array_size: Optional[int] = None
    # For function types, this holds the parameter types and return type
    param_types: Optional[List['SawType']] = None
    func_return_type: Optional['SawType'] = None

    def __repr__(self):
        if self.kind == TypeKind.TUPLE and self.element_types:
            types_str = ", ".join(str(t) for t in self.element_types)
            return f"({types_str})"
        if self.kind == TypeKind.STRUCT and self.struct_name:
            if self.type_args:
                args_str = ", ".join(str(t) for t in self.type_args)
                return f"{self.struct_name}<{args_str}>"
            return self.struct_name
        if self.kind == TypeKind.OPTIONAL and self.inner_type:
            return f"{self.inner_type}?"
        if self.kind == TypeKind.ENUM and self.enum_name:
            if self.type_args:
                args_str = ", ".join(str(t) for t in self.type_args)
                return f"{self.enum_name}<{args_str}>"
            return self.enum_name
        if self.kind == TypeKind.TYPE_PARAM and self.type_param_name:
            return self.type_param_name
        if self.kind == TypeKind.ARRAY and self.array_element_type is not None:
            return f"[{self.array_element_type}; {self.array_size}]"
        if self.kind == TypeKind.FUNCTION:
            params = ", ".join(str(t) for t in (self.param_types or []))
            return f"({params}) -> {self.func_return_type}"
        if self.kind == TypeKind.SELF:
            return "Self"
        return self.kind.name


@dataclass
class TypeParameter:
    """A type parameter in a generic function, struct, or enum (e.g., T in func foo<T>)."""
    name: str
    bounds: List[str] = field(default_factory=list)  # Interface bounds (Phase 3)
    line: int = 0
    column: int = 0


# Base AST Node - no default values to avoid inheritance issues
@dataclass
class ASTNode:
    pass


# Expressions
@dataclass
class Expression(ASTNode):
    pass


@dataclass
class Argument:
    """A function/method/enum call argument - can be named or positional."""
    value: 'Expression'
    name: Optional[str] = None  # None for positional, string for named

    @property
    def is_named(self) -> bool:
        return self.name is not None


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
    type_args: Optional[List['SawType']] = None  # For generic type access: Option<Int>
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
class MoveExpr(Expression):
    """Move expression: move variable - transfers ownership without copying."""
    variable: str  # The variable name being moved
    line: int = 0
    column: int = 0


@dataclass
class FunctionCall(Expression):
    """Function call: name(args) or name<T>(args). Arguments can be positional or named."""
    name: str
    arguments: List[Argument]
    type_args: Optional[List['SawType']] = None  # For generic calls: identity<Int>(x)
    line: int = 0
    column: int = 0


@dataclass
class IfExpr(Expression):
    condition: Expression
    then_branch: 'Block'
    else_branch: Optional['Block'] = None
    line: int = 0
    column: int = 0


@dataclass
class TupleLiteral(Expression):
    elements: List[Expression]
    line: int = 0
    column: int = 0


@dataclass
class TupleIndex(Expression):
    tuple_expr: Expression
    index: int
    line: int = 0
    column: int = 0


@dataclass
class ArrayLiteral(Expression):
    """Array literal: [1, 2, 3]"""
    elements: List[Expression]
    line: int = 0
    column: int = 0


@dataclass
class ArrayIndex(Expression):
    """Array indexing: arr[i]"""
    array_expr: Expression
    index: Expression  # Can be any expression that evaluates to Int
    line: int = 0
    column: int = 0


@dataclass
class MemberAccess(Expression):
    """Access a member/field of an expression."""
    object: Expression
    member: str
    line: int = 0
    column: int = 0


@dataclass
class StructInit(Expression):
    """Struct initialization: Point(x: 10, y: 20) or Box<Int>(value: 42)"""
    struct_name: str
    field_inits: List[tuple[str, Expression]]  # [(field_name, value), ...]
    type_args: Optional[List['SawType']] = None  # For generic structs: Box<Int> has type_args=[Int]
    line: int = 0
    column: int = 0
    # Resolution metadata (filled in by type checker)
    resolved_init_params: Optional[List[str]] = None  # None = field init, List = custom init params


@dataclass
class NoneLiteral(Expression):
    """The None literal for optionals."""
    line: int = 0
    column: int = 0
    resolved_type: Optional['SawType'] = None  # Filled in by typechecker


@dataclass
class ForceUnwrap(Expression):
    """Force unwrap: expr!"""
    expr: Expression
    line: int = 0
    column: int = 0


@dataclass
class NilCoalesce(Expression):
    """Nil coalescing: expr ?? default"""
    expr: Expression
    default: Expression
    line: int = 0
    column: int = 0


@dataclass
class OptionalChain(Expression):
    """Optional chaining: expr?.member"""
    expr: Expression
    member: str
    line: int = 0
    column: int = 0


@dataclass
class MethodCall(Expression):
    """Method or enum variant call: object.method(args) or EnumType.Variant(args)

    The type checker disambiguates based on whether 'object' refers to an enum type.
    Arguments can be positional or named (name: value).
    """
    object: Expression
    method_name: str
    arguments: List[Argument]
    line: int = 0
    column: int = 0


@dataclass
class SelfExpr(Expression):
    """The 'self' keyword"""
    line: int = 0
    column: int = 0


@dataclass
class IfLetExpr(Expression):
    """Optional binding: if let/var x = optional { ... } else { ... }"""
    name: str
    optional_expr: Expression
    mutable: bool  # True for 'if var', False for 'if let'
    then_branch: 'Block'
    else_branch: Optional['Block'] = None
    line: int = 0
    column: int = 0


@dataclass
class GuardLetStatement(ASTNode):
    """Guard statement: guard let/var x = optional else { return }"""
    name: str
    optional_expr: Expression
    mutable: bool  # True for 'guard var', False for 'guard let'
    else_branch: 'Block'  # Must contain early exit (return, break, etc.)
    line: int = 0
    column: int = 0


@dataclass
class EnumInit(Expression):
    """Enum variant initialization: Status.Success or Status.Error(code: 404)
    or Option<Int>.Some(value: 42) for generic enums.

    Created by the type checker from MethodCall when the base is an enum type.
    Arguments can be positional or named.
    """
    enum_name: str
    variant_name: str
    arguments: List[Argument]
    type_args: Optional[List['SawType']] = None  # For generic enums: Option<Int> has type_args=[Int]
    line: int = 0
    column: int = 0


@dataclass
class MatchArm(ASTNode):
    """Match arm: case VariantName(binding1, binding2) -> expression"""
    variant_name: str
    bindings: List[str]  # Variable names to bind associated values to
    body: Expression  # Can be an expression or a Block
    line: int = 0
    column: int = 0


@dataclass
class MatchExpr(Expression):
    """Match expression: match value { case Variant1 -> expr1, case Variant2 -> expr2 }"""
    matched_expr: Expression
    arms: List[MatchArm]
    line: int = 0
    column: int = 0


@dataclass
class RangeExpr(Expression):
    """Range expression: start..end (exclusive)"""
    start: Expression
    end: Expression
    line: int = 0
    column: int = 0


@dataclass
class ClosureParam:
    """A parameter in a closure expression."""
    name: str
    type_annotation: Optional[SawType] = None
    line: int = 0
    column: int = 0


@dataclass
class ClosureExpr(Expression):
    """Closure expression: { x in x * 2 } or { $0 * 2 }

    Supports three forms:
    1. Named parameters: { x, y in x + y }
    2. Shorthand parameters: { $0 + $1 }
    3. No parameters: { 42 } (treated as () -> T)
    """
    parameters: List[ClosureParam]  # Named parameters, empty for shorthand
    body: 'Block'
    shorthand_param_count: int = 0  # Number of $0, $1, etc. used
    captures: List[str] = field(default_factory=list)  # Filled by type checker
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
    target: Expression  # Can be Identifier or MemberAccess
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
class WhileExpr(Expression):
    condition: Optional[Expression]  # None for infinite loop
    body: 'Block'
    line: int = 0
    column: int = 0


@dataclass
class BreakStatement(Statement):
    value: Optional[Expression] = None  # Optional break value
    line: int = 0
    column: int = 0


@dataclass
class ContinueStatement(Statement):
    line: int = 0
    column: int = 0


@dataclass
class ForLoop(Statement):
    """For loop: for variable in iterable { body }"""
    variable: str
    iterable: Expression  # Usually a RangeExpr
    body: 'Block'
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
class StructField:
    """A field in a struct declaration."""
    name: str
    type: SawType


@dataclass
class Struct(ASTNode):
    """Struct declaration: struct Point { x: Int, y: Int } or struct Box<T> { value: T }"""
    name: str
    fields: List[StructField]
    type_params: List['TypeParameter'] = field(default_factory=list)
    line: int = 0
    column: int = 0


@dataclass
class EnumVariant:
    """A variant in an enum declaration."""
    name: str
    associated_types: List[tuple[str, SawType]]  # [(param_name, type), ...]


@dataclass
class Enum(ASTNode):
    """Enum declaration: enum Status { case Success } or enum Option<T> { case Some(value: T), case None }"""
    name: str
    variants: List[EnumVariant]
    type_params: List['TypeParameter'] = field(default_factory=list)
    line: int = 0
    column: int = 0


@dataclass
class InterfaceMethod(ASTNode):
    """Method signature in an interface (no body)."""
    name: str
    parameters: List[Parameter]  # includes self
    return_type: SawType
    self_mutable: bool = False  # True for 'var self'
    line: int = 0
    column: int = 0


@dataclass
class AssociatedType(ASTNode):
    """Associated type declaration in an interface: type Item"""
    name: str
    bounds: List[str] = field(default_factory=list)  # Interface bounds (future)
    line: int = 0
    column: int = 0


@dataclass
class Interface(ASTNode):
    """Interface declaration: interface CustomCopy: Deinit { func copy(self) -> Self }"""
    name: str
    methods: List[InterfaceMethod]  # Required method signatures
    associated_types: List[AssociatedType] = field(default_factory=list)
    type_params: List[TypeParameter] = field(default_factory=list)
    parent_interfaces: List[str] = field(default_factory=list)  # Inherited interfaces
    line: int = 0
    column: int = 0


@dataclass
class TypeAssignment(ASTNode):
    """Type assignment in an extension: type Item = Int"""
    name: str  # Associated type name
    assigned_type: 'SawType'  # The concrete type
    line: int = 0
    column: int = 0


@dataclass
class Extension(ASTNode):
    """Extension declaration: extension Box<T>: Interface { ... }"""
    struct_name: str
    methods: List['Method']
    type_params: List['TypeParameter'] = field(default_factory=list)  # For generic extensions
    conformances: List[str] = field(default_factory=list)  # Interface names
    type_assignments: List[TypeAssignment] = field(default_factory=list)  # Associated type assignments
    line: int = 0
    column: int = 0


@dataclass
class Method(ASTNode):
    """Method definition: func name(self, ...) -> Type { ... }"""
    name: str
    parameters: List[Parameter]
    return_type: SawType
    body: Block
    is_init: bool = False  # True for 'init' methods
    self_mutable: bool = False  # True for 'var self'
    line: int = 0
    column: int = 0


@dataclass
class Function(ASTNode):
    name: str
    parameters: List[Parameter]
    return_type: SawType
    body: Block
    type_params: List[TypeParameter] = field(default_factory=list)  # Generic type parameters
    line: int = 0
    column: int = 0


@dataclass
class TypeDefinition(ASTNode):
    """Type definition: type MyInt = Int"""
    name: str
    defined_type: 'SawType'
    line: int = 0
    column: int = 0


@dataclass
class Program(ASTNode):
    structs: List[Struct]
    functions: List[Function]
    extensions: List[Extension] = field(default_factory=list)
    enums: List[Enum] = field(default_factory=list)
    interfaces: List[Interface] = field(default_factory=list)
    type_definitions: List[TypeDefinition] = field(default_factory=list)
    line: int = 0
    column: int = 0

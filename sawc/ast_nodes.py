"""
Saw Language AST Node Definitions
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum, auto


class TypeKind(Enum):
    INT = auto()         # System-width signed integer (typically 64-bit)
    UINT = auto()        # System-width unsigned integer (typically 64-bit)
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
    SELF = auto()        # For Self type in trait methods
    POINTER = auto()     # For raw pointers: UnsafePointer<T>, UnsafeMutablePointer<T>
    MODULE = auto()      # For module references during qualified access
    REFERENCE = auto()   # For reference types: &T (immutable), &var T (mutable)
    EXISTENTIAL = auto() # For `any Trait` type-erased existentials (design 51)
    NEVER = auto()       # Bottom type: the result of a diverging expression
                         # (`panic(...)`). Assignable to any expected type; a
                         # function body ending in one needs no return value
                         # (design 49). NOT a full Never type system — just the
                         # divergence marker the typechecker/codegen need.
    # Fixed-width integers
    INT8 = auto()
    INT16 = auto()
    INT32 = auto()
    INT64 = auto()
    UINT8 = auto()
    UINT16 = auto()
    UINT32 = auto()
    UINT64 = auto()


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
    # For function types (FUNCTION): True for a `sync` function type
    # (`sync (Int) -> Int`) — a checked suspension-free effect context (design
    # 22). Calls through a sync-typed value do not mark the caller suspending; a
    # closure/function assigned to it is checked transitively suspension-free.
    func_is_sync: bool = False
    # For function types (FUNCTION): True when the type is ESCAPING (design 16/29).
    # A closure-typed function PARAMETER is non-escaping by default (`(Int) ->
    # Void`); the `escaping` marker in the post-parameter slot opts out
    # (`(Int) escaping -> Void`, composing as `(Int) sync escaping -> Void`).
    # Function types in any OTHER role (struct field, binding annotation, return
    # type) are IMPLICITLY escaping and carry this bit set by type resolution —
    # writing the marker there is a redundancy error. The bit drives the variance
    # rule: a non-escaping value flows into an escaping slot? NO (the callee may
    # store it); an escaping value into a non-escaping slot? YES (safe — the
    # callee promises not to store it). So non-escaping <: escaping.
    func_is_escaping: bool = False
    # For pointer types (POINTER), True = UnsafePointer (mutable), False = UnsafeConstPointer
    pointer_mutable: Optional[bool] = None
    # For module types (during qualified access)
    module_name: Optional[str] = None
    # For reference types (REFERENCE), True = &var T (mutable), False = &T (immutable)
    reference_mutable: bool = False
    # For EXISTENTIAL types (`any Trait`, design 51): the trait name being erased
    # to. Legal only as `&any Trait` or `Box<any Trait, A>` (unsized discipline);
    # represented at runtime as a fat pointer (data ptr, vtable ptr).
    existential_trait: Optional[str] = None
    # Direct reference to type symbol (StructSymbol, EnumSymbol, etc.)
    symbol: Optional[Any] = None

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
            # The multi-error catch union (design 30 Ruling 2) is a compiler-
            # synthesized, unnameable enum named `_CatchError_<id>`. Never surface
            # that internal name (nor its non-deterministic id) in diagnostics —
            # render it as what it is so the message stays stable and the type
            # reads as unwritable.
            if self.enum_name.startswith("_CatchError_"):
                variants = getattr(self.symbol, "variant_order", None)
                if variants:
                    return f"<error union: {' | '.join(variants)}>"
                return "<error union>"
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
            # Canonical post-parameter effect-slot order: `sync escaping`.
            effects = ""
            if self.func_is_sync:
                effects += " sync"
            if self.func_is_escaping:
                effects += " escaping"
            return f"({params}){effects} -> {self.func_return_type}"
        if self.kind == TypeKind.SELF:
            return "Self"
        if self.kind == TypeKind.POINTER and self.inner_type:
            ptr_name = "UnsafePointer" if self.pointer_mutable else "UnsafeConstPointer"
            return f"{ptr_name}<{self.inner_type}>"
        if self.kind == TypeKind.REFERENCE and self.inner_type:
            if self.reference_mutable:
                return f"&var {self.inner_type}"
            return f"&{self.inner_type}"
        if self.kind == TypeKind.EXISTENTIAL:
            return f"any {self.existential_trait}"
        # Map TypeKind names to CamelCase display names
        display_names = {
            TypeKind.INT: "Int",
            TypeKind.UINT: "UInt",
            TypeKind.INT8: "Int8",
            TypeKind.INT16: "Int16",
            TypeKind.INT32: "Int32",
            TypeKind.INT64: "Int64",
            TypeKind.UINT8: "UInt8",
            TypeKind.UINT16: "UInt16",
            TypeKind.UINT32: "UInt32",
            TypeKind.UINT64: "UInt64",
            TypeKind.FLOAT: "Float",
            TypeKind.BOOL: "Bool",
            TypeKind.STRING: "String",
            TypeKind.VOID: "Void",
        }
        return display_names.get(self.kind, self.kind.name)

    # ===== Predicate Methods =====

    def is_optional(self) -> bool:
        """Check if this is an optional type (T?)."""
        return self.kind == TypeKind.OPTIONAL

    def is_none_literal(self) -> bool:
        """Check if this is a None literal (untyped optional)."""
        return self.kind == TypeKind.OPTIONAL and self.inner_type is None

    def is_function(self) -> bool:
        """Check if this is a function type."""
        return self.kind == TypeKind.FUNCTION

    def is_primitive(self) -> bool:
        """Check if this is a primitive type (Int, Float, Bool, String)."""
        return self.kind in (TypeKind.INT, TypeKind.FLOAT, TypeKind.BOOL, TypeKind.STRING)

    def is_struct(self) -> bool:
        """Check if this is a struct type."""
        return self.kind == TypeKind.STRUCT

    def is_enum(self) -> bool:
        """Check if this is an enum type."""
        return self.kind == TypeKind.ENUM

    def is_result(self) -> bool:
        """Check if this is a Result<T, E> type.

        Note: The parser creates generic types as STRUCT, but Result is actually
        an enum. We check both possibilities here.
        """
        if self.kind == TypeKind.ENUM and self.enum_name == "Result":
            return True
        # Parser creates generic types as STRUCT - check struct_name too
        if self.kind == TypeKind.STRUCT and self.struct_name == "Result":
            return True
        return False

    def unwrap_result_ok(self) -> Optional['SawType']:
        """Get the T from Result<T, E>, or None if not a Result."""
        if self.is_result() and self.type_args and len(self.type_args) >= 1:
            return self.type_args[0]
        return None

    def unwrap_result_err(self) -> Optional['SawType']:
        """Get the E from Result<T, E>, or None if not a Result."""
        if self.is_result() and self.type_args and len(self.type_args) >= 2:
            return self.type_args[1]
        return None

    def is_tuple(self) -> bool:
        """Check if this is a tuple type."""
        return self.kind == TypeKind.TUPLE

    def is_array(self) -> bool:
        """Check if this is an array type."""
        return self.kind == TypeKind.ARRAY

    def is_reference_type(self) -> bool:
        """Check if this is a reference type (&T or &var T)."""
        return self.kind == TypeKind.REFERENCE

    def is_existential(self) -> bool:
        """Check if this is an `any Trait` existential type (design 51)."""
        return self.kind == TypeKind.EXISTENTIAL

    # ===== Transformation Methods =====

    def unwrap_optional(self) -> 'SawType':
        """Get the inner type of an optional, or self if not optional."""
        if self.kind == TypeKind.OPTIONAL and self.inner_type:
            return self.inner_type
        return self

    def wrap_optional(self) -> 'SawType':
        """Wrap this type in an optional (T -> T?)."""
        return SawType(TypeKind.OPTIONAL, inner_type=self)

    def unwrap_reference(self) -> 'SawType':
        """Get the inner type of a reference, or self if not a reference."""
        if self.kind == TypeKind.REFERENCE and self.inner_type:
            return self.inner_type
        return self

    def substitute(self, type_map: Dict[str, 'SawType']) -> 'SawType':
        """Substitute type parameters with concrete types.

        Args:
            type_map: Mapping from type parameter names to concrete types

        Returns:
            A new SawType with type parameters replaced by their concrete types
        """
        # Handle type parameters (T, U, etc.)
        if self.kind == TypeKind.TYPE_PARAM and self.type_param_name:
            if self.type_param_name in type_map:
                return type_map[self.type_param_name]
            return self

        # Handle struct types (may have type args, or name might be a type param)
        if self.kind == TypeKind.STRUCT and self.struct_name:
            # Check if struct name is actually a type parameter
            if self.struct_name in type_map:
                return type_map[self.struct_name]
            # Substitute in type arguments
            if self.type_args:
                substituted_args = [t.substitute(type_map) for t in self.type_args]
                return SawType(TypeKind.STRUCT, struct_name=self.struct_name, type_args=substituted_args)
            return self

        # Handle enum types (may have type args)
        if self.kind == TypeKind.ENUM and self.enum_name:
            if self.type_args:
                substituted_args = [t.substitute(type_map) for t in self.type_args]
                return SawType(TypeKind.ENUM, enum_name=self.enum_name, type_args=substituted_args)
            return self

        # Handle optional types
        if self.kind == TypeKind.OPTIONAL and self.inner_type:
            substituted_inner = self.inner_type.substitute(type_map)
            return SawType(TypeKind.OPTIONAL, inner_type=substituted_inner)

        # Handle pointer types
        if self.kind == TypeKind.POINTER and self.inner_type:
            substituted_inner = self.inner_type.substitute(type_map)
            return SawType(TypeKind.POINTER, inner_type=substituted_inner, pointer_mutable=self.pointer_mutable)

        # Handle reference types
        if self.kind == TypeKind.REFERENCE and self.inner_type:
            substituted_inner = self.inner_type.substitute(type_map)
            return SawType(TypeKind.REFERENCE, inner_type=substituted_inner, reference_mutable=self.reference_mutable)

        # Handle tuple types
        if self.kind == TypeKind.TUPLE and self.element_types:
            substituted_elements = [t.substitute(type_map) for t in self.element_types]
            return SawType(TypeKind.TUPLE, element_types=substituted_elements)

        # Handle array types
        if self.kind == TypeKind.ARRAY and self.array_element_type:
            substituted_element = self.array_element_type.substitute(type_map)
            return SawType(TypeKind.ARRAY, array_element_type=substituted_element, array_size=self.array_size)

        # Handle function types
        if self.kind == TypeKind.FUNCTION:
            substituted_params = [t.substitute(type_map) for t in (self.param_types or [])]
            substituted_return = self.func_return_type.substitute(type_map) if self.func_return_type else None
            return SawType(TypeKind.FUNCTION, param_types=substituted_params, func_return_type=substituted_return, func_is_sync=self.func_is_sync, func_is_escaping=self.func_is_escaping)

        # Primitives and other types don't need substitution
        return self


@dataclass
class TypeParameter:
    """A type parameter in a generic function, struct, or enum (e.g., T in func foo<T>)."""
    name: str
    bounds: List[str] = field(default_factory=list)  # Trait bounds (Phase 3)
    # Default type for an omitted trailing argument (design 37): the `Global` in
    # `struct Vector<T, A: Allocator = Global>`. TYPES only — no value defaults.
    # When a reference site omits this (and every following) parameter, the
    # default is substituted BEFORE mangling, so `Vector<Int>` and
    # `Vector<Int, Global>` collapse to one identity / one monomorphization.
    default: Optional['SawType'] = None
    line: int = 0
    column: int = 0


class Visibility(Enum):
    """Visibility modifier for declarations."""
    PRIVATE = auto()   # Default - only visible in current module
    PUBLIC = auto()    # Visible everywhere
    PACKAGE = auto()   # public(package) - visible within the package
    PARENT = auto()    # public(parent) - visible to parent module


@dataclass
class ImportDecl:
    """Import declaration: import std.io or import std.io.{File, Directory}"""
    path: List[str]                    # ["std", "io"]
    symbols: Optional[List[str]]       # ["File", "Directory"] or None for module import
    alias: Optional[str]               # For 'as name' syntax (module alias)
    is_glob: bool = False              # For import foo.*
    line: int = 0
    column: int = 0
    # Per-symbol aliases for selective imports (design 53): original name ->
    # local name, e.g. `import std.io.{Read as R}` -> {"Read": "R"}. A symbol
    # with no alias is absent here (imported under its own name).
    symbol_aliases: Optional[dict] = None


@dataclass
class StaticAssert:
    """Compile-time assertion `static_assert(<const-expr>, "message")` (design
    53). Legal at top level and in statement position. The condition is
    evaluated by the const evaluator; a false result is a compile error carrying
    the message, a true result emits no code."""
    condition: 'Expression'
    message: str
    line: int = 0
    column: int = 0


@dataclass
class ModuleDecl:
    """Module declaration: module parser or public module runtime"""
    name: str
    is_public: bool = False
    is_inline: bool = False            # True for inline module { ... }
    body: Optional['Program'] = None   # For inline modules
    line: int = 0
    column: int = 0


@dataclass
class ExportDecl:
    """Export declaration in init.saw facade files.

    Syntax:
    - export internal.foobar.FooImpl as Foo  # Re-export with rename
    - export utils                            # Re-export module
    - export internal.foobar.*               # Re-export all public symbols
    """
    path: List[str]                    # Path to symbol/module being exported
    alias: Optional[str] = None        # Name to export as (None = use last component)
    is_glob: bool = False              # True for export foo.*
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
    # Fixed-width suffix (design 53): one of i8/i16/i32/i64/u8/u16/u32/u64 when
    # the literal was written `255u8`; None means a platform `Int` literal.
    suffix: Optional[str] = None


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
class StringInterpolation(Expression):
    """String with interpolated expressions: "Hello {name}!"

    parts[0] + expressions[0] + parts[1] + expressions[1] + ... + parts[n]
    len(parts) == len(expressions) + 1
    """
    parts: List[str]           # String literals between expressions
    expressions: List['Expression']  # Interpolated expressions
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
    """Move expression: move variable - transfers ownership without copying.

    `variable` names the root binding (always present). `path` is set only for
    a *partial* move like `move p.x`, `move p.x.y`, or `move arr[i]`: it holds
    the projected lvalue expression rooted at `variable`. Partial moves are
    forbidden on every struct (design 35) -- the parser accepts the syntax so a
    deliberate typechecker diagnostic (naming the field and base) can reject it,
    rather than a bare parse error or silent mis-handling.
    """
    variable: str  # The root binding name being moved
    path: Optional['Expression'] = None  # Projected lvalue for a partial move
    line: int = 0
    column: int = 0


@dataclass
class ReferenceExpr(Expression):
    """Reference expression at call site: &expr or &var expr.

    Used when passing arguments to functions that take reference parameters.
    The mutable flag indicates whether this is a mutable reference (&var).
    `in_argument_position` is set by the parser when the reference is the whole
    of a call/method/init argument; a `&var` reference anywhere else (design 34)
    is rejected by the typechecker.
    """
    expr: Expression
    mutable: bool = False  # True for &var, False for &
    in_argument_position: bool = False  # Set by the parser for call arguments
    line: int = 0
    column: int = 0


@dataclass
class CastExpr(Expression):
    """Type cast expression: expr as Type."""
    expr: Expression
    target_type: 'SawType'
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
class OptionalWrap(Expression):
    """Wraps a value T into Optional<T> (Some).

    Inserted by typechecker when T is used where T? is expected.
    """
    value: Expression
    target_type: Optional['SawType'] = None  # The full T? type
    line: int = 0
    column: int = 0
    # Synthesized by the typechecker, so it never flows through the
    # _check_expression chokepoint; carry its type explicitly for codegen.
    resolved_type: Optional['SawType'] = None

    def __post_init__(self):
        if self.resolved_type is None:
            self.resolved_type = self.target_type


@dataclass
class ResultOkWrap(Expression):
    """Wraps a value T into Result<T, E> as Ok.

    Inserted by typechecker when T is returned from a Result<T, E> function.
    """
    value: Expression
    result_type: Optional['SawType'] = None  # The full Result<T, E> type
    line: int = 0
    column: int = 0
    # Synthesized by the typechecker (bypasses the _check_expression
    # chokepoint); carry its type explicitly for codegen.
    resolved_type: Optional['SawType'] = None

    def __post_init__(self):
        if self.resolved_type is None:
            self.resolved_type = self.result_type


@dataclass
class ResultErrWrap(Expression):
    """Wraps a value E into Result<T, E> as Err.

    Inserted by typechecker when E is returned from a Result<T, E> function.
    """
    value: Expression
    result_type: Optional['SawType'] = None  # The full Result<T, E> type
    line: int = 0
    column: int = 0
    # Synthesized by the typechecker (bypasses the _check_expression
    # chokepoint); carry its type explicitly for codegen.
    resolved_type: Optional['SawType'] = None

    def __post_init__(self):
        if self.resolved_type is None:
            self.resolved_type = self.result_type


@dataclass
class ErasedErrWrap(Expression):
    """Wraps a concrete error value E into Result<T, Box<any Error>> as Err,
    erasing E into a `Box<any Trait>` first (design 56 N3 erased Results).

    Inserted by the typechecker when a concrete `E: Error` is returned from a
    function declared to return an erased Result. Codegen boxes the value
    (through `allocator`, Global by default) with the (E, trait) vtable, then
    builds the Err payload from the fat pointer.
    """
    value: Expression
    result_type: Optional['SawType'] = None   # Result<T, Box<any Trait>>
    concrete_err: Optional['SawType'] = None   # E
    trait_name: str = "Error"
    allocator: Optional['SawType'] = None      # Global by default
    line: int = 0
    column: int = 0
    resolved_type: Optional['SawType'] = None

    def __post_init__(self):
        if self.resolved_type is None:
            self.resolved_type = self.result_type


@dataclass
class TryExpr(Expression):
    """Try expression: unwraps Ok, propagates/handles Err.

    Variants:
    - try expr: Unwraps Ok, propagates Err (requires catch or error-returning function)
    - try? expr: Converts Result<T, E> to T? (returns None on Err)
    - try! expr: Unwraps Ok, panics on Err (like force unwrap)
    """
    expr: Expression
    variant: str  # "propagate", "optional", or "force"
    catch_block: Optional['Block'] = None  # For inline catch: try expr catch { ... }
    line: int = 0
    column: int = 0


@dataclass
class TryCatchExpr(Expression):
    """Try-catch block expression for local error handling.

    Syntax: try { ... } catch { handle }

    The try_block can contain multiple try expressions.
    Unhandled errors propagate to the catch block.
    The caught error is available as 'error' variable in catch block.
    """
    try_block: 'Block'
    catch_block: 'Block'
    error_binding: Optional[str] = None  # Optional name for caught error (default: "error")
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
    # Explicit method-level type arguments (brief 36): `v.map<Int>(...)`. None
    # when the call supplies none. Inference is future work, so a generic method
    # requires these to be written explicitly.
    type_args: Optional[List['SawType']] = None
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
    enum_symbol: Optional[Any] = None  # For module-qualified enums: direct symbol reference
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
    """Range expression: `start..end` (exclusive) or `start..=end` (inclusive,
    design 53). An inclusive range lowers to the Int.max-safe `RangeInclusive`
    iterator, never to a `start..(end + 1)` desugar."""
    start: Expression
    end: Expression
    line: int = 0
    column: int = 0
    is_inclusive: bool = False


@dataclass
class ClosureParam:
    """A parameter in a closure expression."""
    name: str
    type_annotation: Optional[SawType] = None
    is_reference: bool = False       # True for `&data` / `&var data` params
    reference_mutable: bool = False  # True for `&var data`
    line: int = 0
    column: int = 0


@dataclass
class CaptureSpec:
    """One entry in a closure's bracketed capture list (design 16/29):
    `[&var sum, move conn, copy v, x]`. `mode` is one of:
      'ref'      — `&name`     immutable borrow (env-of-references)
      'ref_var'  — `&var name` mutable borrow  (env-of-references)
      'move'     — `move name` ownership transfer into the env
      'copy'     — `copy name` explicit deep copy into the env
      'plain'    — `name`      today's transfer rules (bitwise / retain / error)
    Borrow captures ('ref'/'ref_var') are legal ONLY in a closure literal passed
    directly to a non-escaping parameter.
    """
    name: str
    mode: str
    line: int = 0
    column: int = 0


@dataclass
class ClosureExpr(Expression):
    """Closure expression: { x in x * 2 } or { $0 * 2 }

    Supports three forms:
    1. Named parameters: { x, y in x + y }
    2. Shorthand parameters: { $0 + $1 }
    3. No parameters: { 42 } (treated as () -> T)

    An optional bracketed capture list may precede the parameters:
    `{ [&var sum] x in ... }`, `{ [move conn] in ... }`.
    """
    parameters: List[ClosureParam]  # Named parameters, empty for shorthand
    body: 'Block'
    shorthand_param_count: int = 0  # Number of $0, $1, etc. used
    capture_specs: List['CaptureSpec'] = field(default_factory=list)  # Parsed [..]
    captures: List[str] = field(default_factory=list)  # Filled by type checker
    # Filled by type checker: name -> effective capture mode (see CaptureSpec).
    capture_modes: Dict[str, str] = field(default_factory=dict)
    has_reference_params: bool = False  # Filled by type checker (design 21 item 3)
    escapes: bool = False  # Filled by type checker (design 21b E1): the closure
                           # value outlives its creating frame (bound/returned/
                           # passed to spawn), so its env is heap-allocated.
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
class CompoundAssignStatement(Statement):
    """Compound assignment: x += 1, y -= 2, etc."""
    target: Expression  # Can be Identifier, MemberAccess, or ArrayIndex
    op: str  # '+', '-', '*', '/', '%'
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
    result_type: Optional['SawType'] = None  # Set by typechecker for expression context


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
    result_type: Optional['SawType'] = None  # Set by typechecker for expression context


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
    default_value: Optional['Expression'] = None  # For default parameter values
    is_reference: bool = False  # True if parameter type is &T or &var T
    reference_mutable: bool = False  # True if parameter type is &var T


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
    visibility: 'Visibility' = Visibility.PRIVATE
    line: int = 0
    column: int = 0
    source_file: str = ""


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
    visibility: 'Visibility' = Visibility.PRIVATE
    line: int = 0
    column: int = 0
    source_file: str = ""


@dataclass
class TraitMethod(ASTNode):
    """Method signature in a trait, optionally with a default body (design 56)."""
    name: str
    parameters: List[Parameter]  # includes self
    return_type: SawType
    self_mutable: bool = False  # True for '&var self'
    self_is_reference: bool = False  # True for '&self' or '&var self'
    is_sync: bool = False  # `func m(...) sync` — a checked suspension-free method
    # Default method body (design 56): a trait method declared WITH a `{ ... }`
    # body is a default. Conformers may omit it (the compiler synthesizes a
    # per-conformer Method from this body) or override it. None = required method.
    body: Optional['Block'] = None
    line: int = 0
    column: int = 0


@dataclass
class AssociatedType(ASTNode):
    """Associated type declaration in a trait: type Item"""
    name: str
    bounds: List[str] = field(default_factory=list)  # Trait bounds (future)
    line: int = 0
    column: int = 0


@dataclass
class Trait(ASTNode):
    """Trait declaration: trait ImplicitCopy: Deinit { func copy(self) -> Self }"""
    name: str
    methods: List[TraitMethod]  # Required method signatures
    associated_types: List[AssociatedType] = field(default_factory=list)
    type_params: List[TypeParameter] = field(default_factory=list)
    parent_traits: List[str] = field(default_factory=list)  # Inherited traits
    visibility: 'Visibility' = Visibility.PRIVATE
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
    """Extension declaration: extension Box<T>: Trait { ... }

    For generic extensions like `extension Vector<T>`, type_params contains [T].
    For specialized extensions like `extension Vector<String>`, type_args contains [String].
    """
    struct_name: str
    methods: List['Method']
    type_params: List['TypeParameter'] = field(default_factory=list)  # For generic extensions
    type_args: List['Type'] = field(default_factory=list)  # For specialized extensions (e.g., Vector<String>)
    conformances: List[str] = field(default_factory=list)  # Trait names
    type_assignments: List[TypeAssignment] = field(default_factory=list)  # Associated type assignments
    visibility: 'Visibility' = Visibility.PRIVATE
    line: int = 0
    column: int = 0
    source_file: str = ""


@dataclass
class Method(ASTNode):
    """Method definition: func name(self, ...) -> Type { ... }

    Static methods have no 'self' parameter and are called as StructName.method().
    """
    name: str
    parameters: List[Parameter]
    return_type: SawType
    body: Block
    is_init: bool = False  # True for 'init' methods
    self_mutable: bool = False  # True for '&var self'
    self_is_reference: bool = False  # True for '&self' or '&var self'
    is_static: bool = False  # True for methods without 'self' parameter
    is_derived_copy: bool = False  # True for a compiler-synthesized memberwise copy()
    is_derived_equals: bool = False  # True for a compiler-synthesized memberwise equals()
    is_derived_compare: bool = False  # True for a compiler-synthesized lexicographic compare() (design 48)
    is_derived_hash: bool = False  # True for a compiler-synthesized field-streaming hash() (design 48)
    is_sync: bool = False  # True for a `sync func` method (checked suspension-free)
    # Method-level generic type params (brief 36): the `U` in `func map<U>(...)`,
    # distinct from and in addition to the enclosing extension's own type params.
    type_params: List['TypeParameter'] = field(default_factory=list)
    line: int = 0
    column: int = 0
    source_file: str = ""


@dataclass
class Attribute(ASTNode):
    """A Swift-style declaration attribute (design 58): `@name` or `@name("arg")`.

    Attached to the declaration immediately following it. In v1 the legal names
    are `export` and `section`; `export` takes zero args or one string literal,
    `section` requires exactly one string literal. `arg` is the decoded string
    literal content (no quotes), or None for the bare `@name` form.
    """
    name: str
    arg: Optional[str] = None
    line: int = 0
    column: int = 0


# Known attribute names (design 58 v1). Used for the unknown-name diagnostic.
KNOWN_ATTRIBUTES = ("export", "section")


def find_attribute(node: 'ASTNode', name: str) -> Optional['Attribute']:
    """Return the `Attribute` with the given name on `node`, or None."""
    for attr in getattr(node, 'attributes', None) or []:
        if attr.name == name:
            return attr
    return None


def is_exported(node: 'ASTNode') -> bool:
    """True if `node` carries an `@export` attribute."""
    return find_attribute(node, 'export') is not None


def export_symbol(node: 'ASTNode') -> Optional[str]:
    """The C symbol name an `@export` requests: the given `@export("sym")`
    string, else the declaration's own name. None if not exported."""
    attr = find_attribute(node, 'export')
    if attr is None:
        return None
    return attr.arg if attr.arg else getattr(node, 'name', None)


def section_name(node: 'ASTNode') -> Optional[str]:
    """The object-file section requested by `@section("name")`, or None."""
    attr = find_attribute(node, 'section')
    return attr.arg if attr is not None else None


@dataclass
class Function(ASTNode):
    name: str
    parameters: List[Parameter]
    return_type: SawType
    body: Block
    type_params: List[TypeParameter] = field(default_factory=list)  # Generic type parameters
    visibility: 'Visibility' = Visibility.PRIVATE
    # `sync func` declaration (design 22): body checked transitively
    # suspension-free at definition (ISR/callback style).
    is_sync: bool = False
    # Declaration attributes (design 58): `@export` / `@section(...)` lines.
    attributes: List['Attribute'] = field(default_factory=list)
    line: int = 0
    column: int = 0
    source_file: str = ""


@dataclass
class TypeDefinition(ASTNode):
    """Type definition: type MyInt = Int"""
    name: str
    defined_type: 'SawType'
    visibility: 'Visibility' = Visibility.PRIVATE
    line: int = 0
    column: int = 0


@dataclass
class StaticDecl(ASTNode):
    """Module-level static declaration: static NAME: Type = initializer (design 41).

    Statics are Sync-only, const-initialized, immortal (never deinit), and there
    is NO `static mut` — global mutation flows only through interior-synchronized
    types (e.g. Atomic<Int>). `initializer` is None for a bare zero-init
    declaration (`static BUF: [Int8; 4096]`), which is only permitted for POD /
    fixed-array statics.
    """
    name: str
    type: 'SawType'
    initializer: Optional['Expression'] = None
    visibility: 'Visibility' = Visibility.PRIVATE
    # Declaration attributes (design 58): `@export` / `@section(...)` lines.
    attributes: List['Attribute'] = field(default_factory=list)
    line: int = 0
    column: int = 0
    source_file: str = ""


@dataclass
class ExternFunction(ASTNode):
    """External function declaration (no body) for FFI."""
    name: str
    parameters: List[Parameter]
    return_type: 'SawType'
    is_variadic: bool = False  # True for functions like printf, open that take ...
    # `extern blocking func` (design 18/22): an unbounded FFI call. For this
    # prototype it is simply a suspension source; the pool-offload machinery
    # (hosted) / freestanding-hazard handling is future work.
    is_blocking: bool = False
    line: int = 0
    column: int = 0


@dataclass
class ExternBlock(ASTNode):
    """extern "C" { ... } block for FFI declarations."""
    abi: str  # "C" for now
    functions: List[ExternFunction]
    line: int = 0
    column: int = 0


@dataclass
class Program(ASTNode):
    structs: List[Struct]
    functions: List[Function]
    extensions: List[Extension] = field(default_factory=list)
    enums: List[Enum] = field(default_factory=list)
    traits: List[Trait] = field(default_factory=list)
    type_definitions: List[TypeDefinition] = field(default_factory=list)
    extern_blocks: List[ExternBlock] = field(default_factory=list)
    statics: List['StaticDecl'] = field(default_factory=list)
    # Module system
    imports: List['ImportDecl'] = field(default_factory=list)
    module_decls: List['ModuleDecl'] = field(default_factory=list)
    exports: List['ExportDecl'] = field(default_factory=list)  # For init.saw facades
    static_asserts: List['StaticAssert'] = field(default_factory=list)  # design 53
    source_path: Optional[str] = None      # Path to source file
    module_path: Optional[List[str]] = None  # Fully qualified module path
    line: int = 0
    column: int = 0

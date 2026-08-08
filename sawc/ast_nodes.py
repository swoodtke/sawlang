"""
Saw Language AST Node Definitions
"""

import copy as _copy
import dataclasses
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum, auto


def annotation(default=None, **kwargs):
    """Declare a cross-pass ANNOTATION field (design 126 R1).

    An annotation is metadata one pass stamps for a later one -- a resolved
    symbol, a dispatch decision, a plan -- as opposed to tree STRUCTURE (an
    operand, a body, an argument list). The distinction matters because the
    compiler has two kinds of reflective walker:

      * child walkers (the coroutine transform's hoist / CFG scans) must visit
        only structure. An annotation may ALIAS a node reachable elsewhere, or
        hold a derived node that a later pass rebuilds, so following one makes a
        walker visit the same call twice or visit a stale copy.
      * `substitute_ast_types` (the monomorphizer) must visit EVERYTHING,
        annotations included -- that is exactly the RC-2 bug R1 fixes.

    So annotations stay declared, typed and visible to `dataclasses.fields()`,
    and child walkers filter them out with `structural_fields()`.
    """
    md = dict(kwargs.pop("metadata", {}))
    md["saw_annotation"] = True
    return field(default=default, metadata=md, **kwargs)


def structural_fields(node):
    """`dataclasses.fields(node)` minus the cross-pass annotations -- i.e. the
    fields that are genuine tree structure. See `annotation()`."""
    return [f for f in dataclasses.fields(node)
            if not f.metadata.get("saw_annotation", False)]


def self_by_pointer(method) -> bool:
    """Does this method receive `self` as a POINTER rather than by value?

    Two spellings say yes. `&var self` is the obvious one (design 40): the
    method mutates its receiver, so it needs the caller's storage.

    A `borrows` accessor is the other, and it is the one place in the language
    where a `&self` spelling does not mean shared-only (design 146, DF-146b).
    A borrows body lends a place OUT of the receiver, and design 141 decision 3
    puts the window's mutability at the USE SITE, not on the declaration -- so
    the receiver has to arrive as storage whichever flavor the use site picks,
    or `v[i].n += 1` would write to the callee's copy. The polymorphism stops
    at the `lend`: everything else in the body is ordinary `&self` code.
    """
    return bool(getattr(method, 'self_mutable', False)
                or getattr(method, 'place_self_by_pointer', False))


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
    CONST_VALUE = auto() # A const generic ARGUMENT: the `256` in `FixedBuf<256>`
                         # (design 148). It rides the type-argument list because
                         # that is what it is — a member of the tuple that
                         # identifies an instantiation — so substitution,
                         # mangling and type equality all reach it through
                         # machinery that already existed. `const_value` holds
                         # the integer; `inner_type` its declared Int/UInt type.
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


def const_expr_str(expr) -> str:
    """Render a constant expression the way its author wrote it (design 148).

    Used where a length or a const argument has not been evaluated yet — inside
    the abstract half of a generic body, `[UInt8; N]` has no number, and a
    diagnostic there has to name `N`. Covers exactly the const grammar; anything
    else falls back to a placeholder rather than raising, since this only ever
    feeds a message.
    """
    if expr is None:
        return "?"
    name = type(expr).__name__
    if name in ("IntLiteral", "BoolLiteral"):
        return str(expr.value)
    if name == "Identifier":
        return expr.name
    if name == "UnaryOp":
        sep = " " if expr.op == "not" else ""
        return f"{expr.op}{sep}{const_expr_str(expr.operand)}"
    if name == "BinaryOp":
        return (f"{const_expr_str(expr.left)} {expr.op} "
                f"{const_expr_str(expr.right)}")
    if name == "FunctionCall":
        args = ", ".join(str(t) for t in (expr.type_args or []))
        return f"{expr.name}<{args}>()" if args else f"{expr.name}()"
    if name == "MemberAccess":
        return f"{const_expr_str(expr.object)}.{expr.member}"
    return "?"


@dataclass
class SawType:
    kind: TypeKind
    # For tuple types, this holds the element types
    element_types: Optional[List['SawType']] = None
    # For NAMED tuple types (design 63): field names aligned with element_types
    # (`(x: Int, y: Int)`). None for a positional tuple. Names + order + types are
    # all part of the type; a named and a positional tuple of the same shape are
    # mutually compatible (labels are a view over the positional layout).
    tuple_field_names: Optional[List[str]] = None
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
    # For an array whose length is written as something other than a literal
    # (design 148): the const expression as parsed. `array_size` is filled in
    # the moment the expression can be evaluated — at type resolution for a
    # ground length like `[Int8; 2 * 128]`, at substitution for a symbolic one
    # like `[UInt8; N]`. Everything downstream reads `array_size`, so an array
    # that has reached codegen always has a number; this field is what carries
    # the length through the abstract half of a generic body, where it does not.
    array_size_expr: Optional[Any] = None
    # For CONST_VALUE: the integer this argument denotes.
    const_value: Optional[int] = None
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
    # Did `_stamp_escaping_roles` set `func_is_escaping`, as opposed to the
    # author writing the marker? The redundancy error must fire only for what
    # the AUTHOR wrote, and type resolution can run over one declared type more
    # than once — the coroutine transform re-enters the front half, and design
    # 146 made that the norm rather than the exception. Without this the SECOND
    # pass reads the compiler's own stamp as a redundant marker and rejects a
    # correct program. Same shape as DF-146a's `_derivation_slot`.
    func_escaping_stamped: bool = False
    # For function types (FUNCTION): True for an `unsafe` function type
    # (`(UnsafePointer<T>) unsafe sync -> R`, design 130). A closure whose own
    # body names an unsafe type is an unsafe closure (rule 3 judged per body), so
    # only an `unsafe`-typed slot accepts it; a safe closure flows into either.
    func_is_unsafe: bool = False
    # For function types (FUNCTION): True for a `borrows` function type
    # (`(Int) borrows -> T`, design 141). A borrows function yields a PLACE of T
    # for a window rather than a T value, so the marker is signature-level. v1
    # has no borrows function VALUES: the bit exists so the type grammar can
    # PARSE the spelling and the typechecker can refuse it by name instead of
    # with a syntax error.
    func_is_borrows: bool = False
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
        # Design 144: a named type's slot holds its module-qualified IDENTITY
        # (`Header$m$dep`). This is the RENDERING, so it shows the short name —
        # what the author wrote, in every diagnostic, doc page and AST dump that
        # goes through `str(t)`. Anything comparing types must compare
        # identities instead (`_type_key`), never this string.
        from type_identity import display_name as _short
        if self.kind == TypeKind.TUPLE and self.element_types:
            if self.tuple_field_names:
                types_str = ", ".join(
                    f"{n}: {t}" for n, t in zip(self.tuple_field_names, self.element_types))
            else:
                types_str = ", ".join(str(t) for t in self.element_types)
            return f"({types_str})"
        if self.kind == TypeKind.STRUCT and self.struct_name:
            if self.type_args:
                args_str = ", ".join(str(t) for t in self.type_args)
                return f"{_short(self.struct_name)}<{args_str}>"
            return _short(self.struct_name)
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
                return f"{_short(self.enum_name)}<{args_str}>"
            return _short(self.enum_name)
        if self.kind == TypeKind.TYPE_PARAM and self.type_param_name:
            return self.type_param_name
        if self.kind == TypeKind.CONST_VALUE:
            return str(self.const_value)
        if self.kind == TypeKind.ARRAY and self.array_element_type is not None:
            # A length that has not been evaluated yet renders as what the
            # author wrote (`[UInt8; N]`), which is what a diagnostic inside an
            # abstract generic body has to say — `None` would name nothing.
            size = (self.array_size if self.array_size is not None
                    else const_expr_str(self.array_size_expr))
            return f"[{self.array_element_type}; {size}]"
        if self.kind == TypeKind.FUNCTION:
            params = ", ".join(str(t) for t in (self.param_types or []))
            # Canonical post-parameter effect-slot order (designs 136, 141):
            # `unsafe sync escaping borrows`.
            effects = ""
            if self.func_is_unsafe:
                effects += " unsafe"
            if self.func_is_sync:
                effects += " sync"
            if self.func_is_escaping:
                effects += " escaping"
            if self.func_is_borrows:
                effects += " borrows"
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
            return f"any {_short(self.existential_trait)}"
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
            # The bottom type is WRITTEN `Never` (design 49), so a diagnostic
            # about it has to spell it the way the author would. Without this
            # entry the fallback printed the enum member name, `NEVER`, and hints
            # like "conform it with `extension NEVER: Printable`" named a type
            # nobody can write.
            TypeKind.NEVER: "Never",
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
            return SawType(TypeKind.TUPLE, element_types=substituted_elements,
                           tuple_field_names=self.tuple_field_names)

        # Handle array types. The LENGTH substitutes too since design 148: a
        # `[UInt8; N]` field of a const-generic struct becomes `[UInt8; 256]`
        # here, which is what lets every reader downstream keep treating
        # `array_size` as the plain int it always was.
        if self.kind == TypeKind.ARRAY and self.array_element_type:
            substituted_element = self.array_element_type.substitute(type_map)
            size, size_expr = self._substituted_length(type_map)
            return SawType(TypeKind.ARRAY,
                           array_element_type=substituted_element,
                           array_size=size, array_size_expr=size_expr)

        # Handle function types
        if self.kind == TypeKind.FUNCTION:
            substituted_params = [t.substitute(type_map) for t in (self.param_types or [])]
            substituted_return = self.func_return_type.substitute(type_map) if self.func_return_type else None
            return SawType(TypeKind.FUNCTION, param_types=substituted_params, func_return_type=substituted_return, func_is_sync=self.func_is_sync, func_is_escaping=self.func_is_escaping, func_escaping_stamped=self.func_escaping_stamped, func_is_unsafe=self.func_is_unsafe)

        # Primitives and other types don't need substitution
        return self

    def const_int(self):
        """The integer a CONST_VALUE denotes, folding its expression if needed.

        A const argument written as arithmetic (`Ring<2 * 128>`) reaches some
        paths before any pass has folded it. Folding on read makes every
        consumer — mangling, substitution, the codegen environment — agree that
        `Ring<2 * 128>` and `Ring<256>` are one instantiation, which is the
        property the whole scheme rests on. Closed expressions only; one
        mentioning a parameter has no value yet and answers None.
        """
        if self.const_value is not None:
            return self.const_value
        if self.array_size_expr is None:
            return None
        from const_eval import const_eval, ConstEvalError
        try:
            value = const_eval(self.array_size_expr)
        except ConstEvalError:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        self.const_value = value
        return value

    def _substituted_length(self, type_map):
        """Resolve an array length against a substitution (design 148).

        Returns `(size, size_expr)`. A length that was already a number stays
        one. A symbolic length whose parameters are all bound by `type_map`
        evaluates through the one constant evaluator; one that is still
        partially abstract — a nested generic being substituted a layer at a
        time — keeps its expression and gets resolved on the next pass.
        """
        if self.array_size is not None or self.array_size_expr is None:
            return self.array_size, self.array_size_expr
        env = {}
        for name, t in type_map.items():
            if t is not None and t.kind == TypeKind.CONST_VALUE:
                value = t.const_int()
                if value is None:
                    return None, self.array_size_expr
                env[name] = value
        from const_eval import const_eval, ConstEvalError
        try:
            return int(const_eval(self.array_size_expr, env=env)), self.array_size_expr
        except ConstEvalError:
            return None, self.array_size_expr


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
    # A const VALUE parameter — the `const N: Int` in `struct FixedBuf<const N:
    # Int>` (design 148). `const_type` is its declared Int/UInt type;
    # `const_default_expr` is the `= 256` as parsed. The typechecker evaluates
    # that default into `default` as a CONST_VALUE `SawType`, which is what lets
    # a value default ride design 37's default-argument machinery unchanged —
    # the fillers substitute `tp.default` whatever kind it is.
    is_const: bool = False
    const_type: Optional['SawType'] = None
    const_default_expr: Optional[Any] = None


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


# Base AST Node (design 126 R1). Every node carries its source position and its
# identity. The base is `kw_only` so these fields never occupy a positional slot:
# subclasses keep declaring their own payload fields positionally, exactly as
# before, and `line=`/`column=`/`node_id=` are always passed by keyword.
#
# `node_id` (design 126 R2) is the compiler's ONLY node identity. Nothing may key
# a map or derive a generated name from Python's `id()`, which is an address:
# neither stable across runs (so compiler output was not reproducible) nor
# expressible in the eventual Saw port.
#
# It is assigned from ONE process-global counter, via `default_factory`, so every
# node gets a distinct id no matter who builds it -- the parser, the interpolation
# sub-parser, a per-module parser, or the ~180 nodes the coroutine transform
# synthesizes. A per-instance counter would collide across modules, and a plain
# `= 0` default would give every synthesized node the same id.
_NEXT_NODE_ID = 1


def _next_node_id() -> int:
    global _NEXT_NODE_ID
    node_id = _NEXT_NODE_ID
    _NEXT_NODE_ID += 1
    return node_id


def current_node_id_bound() -> int:
    """The highest id issued so far (design 168 unit 4).

    Stored beside a serialized std graph so a later process can restore it
    without walking it: every node in the blob has an id at or below this.
    """
    return _NEXT_NODE_ID - 1


def seed_node_ids(bound: int) -> None:
    """Advance the allocator past a restored graph (design 168 unit 4).

    `pickle` preserves `node_id` verbatim, so a restored std graph arrives
    holding ids the counter would otherwise hand out again. A collision is
    SILENT: `effects.py` merges two functions' suspend analysis under one key,
    and the coroutine transform's entry-vs-std membership test misfiles a std
    extension as user code. Design 164's prototype hit exactly that on 13 of
    1,114 examples. One assignment closes it, which is why the restore has to
    happen before anything else is parsed.
    """
    global _NEXT_NODE_ID
    if bound >= _NEXT_NODE_ID:
        _NEXT_NODE_ID = bound + 1


@dataclass(kw_only=True)
class ASTNode:
    line: int = 0
    column: int = 0
    node_id: int = field(default_factory=_next_node_id)

    def __deepcopy__(self, memo):
        """Copy the subtree, but give every copied node a FRESH `node_id`.

        This is what keeps `node_id` faithful to the `id()` semantics it
        replaces. The compiler clones AST subtrees to monomorphize generic
        templates and to synthesize trait defaults per conformer; a plain
        deepcopy copies the id field, so two live instantiations would share one
        identity. They would then collide in the effect graph (merging their
        suspend analysis), in the coroutine transform's method tables (last
        clone wins), and in the `_CatchError_<id>` union type name (one
        instantiation's layout silently reused for another). Distinct objects
        get distinct ids -- exactly as distinct addresses did.
        """
        cls = self.__class__
        new = cls.__new__(cls)
        memo[id(self)] = new
        for k, v in self.__dict__.items():
            setattr(new, k, _copy.deepcopy(v, memo))
        new.node_id = _next_node_id()
        return new


# Expressions
#
# `resolved_type` is the typechecker's annotation chokepoint output
# (`_check_expression` stamps it on every expression). Declaring it here rather
# than grafting it at runtime is what lets `dataclasses.fields()`-driven walkers
# -- above all `substitute_ast_types`, the monomorphizer -- actually SEE it, so a
# generic template's types are substituted into its instantiation instead of
# surviving stale (design 126 R1; the RC-2 bug).
@dataclass(kw_only=True)
class Expression(ASTNode):
    resolved_type: Optional['SawType'] = None
    # Annotations the typechecker may stamp on ANY expression, verified by
    # walking the AST of 220 corpus programs (design 126 R1):
    #   autowrap_to_optional -- a bare `T` passed where `T?` is expected: holds
    #                           the FULL `T?` type codegen builds around the
    #                           value (design 57 DF3); None = no wrap
    #   expected_type        -- the type pushed down from context, kept for
    #                           literals/collection literals that need it
    #   needs_copy           -- the move checker decided this operand is copied
    #   closure_lend         -- a closure operand is lent, not transferred
    #   payload_needs_copy   -- design 131: this node EXTRACTS an optional's
    #                           payload out of storage the source keeps (`o!`,
    #                           the `??` left operand, an `if let` binding), and
    #                           the place rule says the extraction retains. The
    #                           retain happens AT the extraction, not at the
    #                           enclosing transfer site, so that a `let`
    #                           initializer -- which never reaches the
    #                           transfer-site copy path -- is covered too.
    #   frame_place_read     -- design 131: the coroutine transform synthesized
    #                           this place out of a frame field. Its ownership
    #                           was settled on the pre-transform AST, so the
    #                           place rule must not re-judge it on the second
    #                           type-check pass.
    #   enum_variant_literal -- design 139: this MemberAccess spells a
    #                           payload-free enum variant (`Slot.Empty`), so it
    #                           CONSTRUCTS a fresh value rather than reading one
    #                           out of storage. It shares a node type with real
    #                           field access, and only the typechecker can tell
    #                           the two apart.
    autowrap_to_optional: Optional['SawType'] = annotation(None)
    expected_type: Optional['SawType'] = annotation(None)
    needs_copy: bool = annotation(False)
    closure_lend: bool = annotation(False)
    payload_needs_copy: bool = annotation(False)
    frame_place_read: bool = annotation(False)
    enum_variant_literal: bool = annotation(False)
    #   resolved_type_identity -- design 144: the module-qualified IDENTITY of
    #                           the type this node's WRITTEN name resolved to
    #                           (an enum-variant literal's enum, a
    #                           `mod.Point(...)` construction's struct). Codegen
    #                           reads it instead of matching the spelling
    #                           against its tables, where two modules' `Color`s
    #                           both live.
    resolved_type_identity: Optional[str] = annotation(None)


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
    # Fixed-width suffix (design 53): one of i8/i16/i32/i64/u8/u16/u32/u64 when
    # the literal was written `255u8`; None means a platform `Int` literal.
    suffix: Optional[str] = None


@dataclass
class FloatLiteral(Expression):
    value: float


@dataclass
class BoolLiteral(Expression):
    value: bool


@dataclass
class StringLiteral(Expression):
    value: str


@dataclass
class StringInterpolation(Expression):
    """String with interpolated expressions: "Hello {name}!"

    parts[0] + expressions[0] + parts[1] + expressions[1] + ... + parts[n]
    len(parts) == len(expressions) + 1
    """
    parts: List[str]           # String literals between expressions
    expressions: List['Expression']  # Interpolated expressions


@dataclass
class FormatPlaceholder(Expression):
    """An EMPTY `{}` inside a string: a positional slot for a format argument.

    Design 137. `"n = {}"` lexes as an interpolated string like any other — the
    braces are there — but the expression between them is empty, so the parser
    records a placeholder here instead of failing. It is legal only as the
    format string of `print`/`panic`/`assert` in a call that supplies a value
    for it; every other position (a bare `let s = "{}"`, a placeholder with no
    argument) is a clean typecheck error, so this node never reaches codegen.

    It carries no expression because the value comes from the call's argument
    list, matched by POSITION. `\\{\\}` is unaffected: escaped braces are
    already marked by the lexer and stay literal text.
    """
    pass


@dataclass
class Identifier(Expression):
    name: str
    type_args: Optional[List['SawType']] = None  # For generic type access: Option<Int>
    # Set when this name resolved to a const generic PARAMETER (design 148), so
    # codegen emits the instantiation's value instead of looking for storage.
    const_param_name: Optional[str] = annotation(None)
    # DF-172j: this name resolved, in a const-required position, to a module
    # `static` the typechecker could fold — an `Int`/`UInt` one initialized by a
    # plain integer literal. `const_static_reject` is the other half: the name IS
    # such a static and is NOT foldable, carrying the reason so the diagnostic
    # can say which rather than implying a static may not be named at all.
    # The evaluator (`const_eval.py`) reads these exactly as it reads the
    # `Int.max` and raw-enum stamps on a MemberAccess, so it never needs a
    # namespace of its own.
    const_static_value: Optional[int] = annotation(None)
    const_static_reject: Optional[str] = annotation(None)


@dataclass
class BinaryOp(Expression):
    op: str
    left: Expression
    right: Expression


@dataclass
class UnaryOp(Expression):
    op: str
    operand: Expression


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
    # design 131: `move o!` — the move is spelled at an optional PROJECTION.
    # It still retires the whole binding (there is no husk state and no partial
    # move); the `!` only says the result is the payload, and it still panics if
    # the optional is dynamically None.
    unwrap: bool = False


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

    # Erasure of a concrete referent to `&any Trait` (design 51 / 126 R1): the
    # concrete type being erased and the trait it is erased to.
    erase_concrete: Optional['SawType'] = annotation(None)
    erase_to_trait: Optional[str] = annotation(None)

    # This `&var` is the one the place transform built out of a `lend` (design
    # 141/146). It is the single exception to the rule that a `&var` projection
    # out of a `&self` receiver is an error: a borrows accessor's receiver is
    # passed by POINTER precisely so the window can write through it, and the
    # window's flavor is chosen at each use site. See `self_by_pointer`.
    from_lend: bool = annotation(False)

    # This reference is the operand of a cast to `UnsafePointer<T>` /
    # `UnsafeConstPointer<T>` — the sanctioned crossing into the unsafe tier
    # (DF-163f), and the only address-of the language has. Set by the
    # typechecker's cast check, which is the node that knows the parent.
    to_pointer_cast: bool = annotation(False)


@dataclass
class CastExpr(Expression):
    """Type cast expression: expr as Type."""
    expr: Expression
    target_type: 'SawType'

    # Design 170: does this integer cast need the runtime representability
    # check? Stamped by the typechecker, which is the pass that knows the Saw
    # types on both sides; codegen emits the compare-and-panic when it is set.
    # False means one of three things, all costing nothing: the pair is TOTAL
    # (widening, or an identity), the operand folded to a value that provably
    # fits, or the node was SYNTHESIZED after type checking (the coroutine
    # transform's pointer and frame casts). That last case is why the default is
    # False rather than True -- an unstamped node keeps the pre-170 lowering
    # instead of acquiring a check nobody reasoned about.
    cast_check: bool = annotation(False)


@dataclass
class FunctionCall(Expression):
    """Function call: name(args) or name<T>(args). Arguments can be positional or named."""
    name: str
    arguments: List[Argument]
    type_args: Optional[List['SawType']] = None  # For generic calls: identity<Int>(x)

    # --- typechecker -> codegen call plan (design 126 R1) ---------------------
    # Binding of source arguments to the callee's LOGICAL parameters (design 66):
    # one slot per parameter holding the source-argument index, or None for a
    # slot the callee fills from its default. None (the whole field) means the
    # legacy positional path -- arguments already line up.
    arg_plan: Optional[List[Optional[int]]] = annotation(None)
    # The callee's mangled symbol, once overload resolution has picked one.
    resolved_symbol: Optional[str] = annotation(None)
    # Set when the call resolves to a STRUCT initializer rather than a function;
    # holds the init's parameter names (design 126 R1 note: distinct from
    # StructInit.resolved_init_params, which is the same idea on the literal).
    resolved_init_params: Optional[List[str]] = annotation(None)
    resolved_field_inits: Optional[List[tuple]] = annotation(None)
    # Builtin construction forms the typechecker recognizes by name.
    is_atomic_construct: bool = annotation(False)
    is_unsafe_mem_construct: bool = annotation(False)
    # `UserId(42)`: the distinct `type` alias this call constructs (design 63).
    # An alias IS its underlying representationally, so codegen compiles the one
    # operand and emits no conversion.
    alias_construction: Optional[str] = annotation(None)
    # `spawn(f(...))`: f's return type, needed to build the task handle.
    spawn_result_type: Optional['SawType'] = annotation(None)
    # True once generic type arguments were INFERRED rather than written.
    type_args_inferred: bool = annotation(False)
    # `__saw_blk_take(job)`: the blocking extern whose result this collects
    # (design 183 unit 2). The job carries one result WORD; the extern's
    # declared return type says what that word is, so both the re-typecheck and
    # codegen read it from here rather than assuming `Int`.
    blk_extern: Optional[str] = annotation(None)


@dataclass
class IfExpr(Expression):
    condition: Expression
    then_branch: 'Block'
    else_branch: Optional['Block'] = None


@dataclass
class TupleLiteral(Expression):
    elements: List[Expression]
    # Field labels for a NAMED tuple literal (design 63): `(x: 3, y: 4)`. None
    # for a positional literal; all-or-nothing (the parser rejects a mix).
    field_names: Optional[List[str]] = None


@dataclass
class TupleIndex(Expression):
    tuple_expr: Expression
    index: int


@dataclass
class ArrayLiteral(Expression):
    """Array literal: [1, 2, 3], or the repeat literal [v; N] (design 148).

    By default lowers to a fixed-size array. When the EXPECTED type (from a
    binding annotation, parameter, return, or struct field) is `Vector<T, A>`,
    the typechecker stamps `vector_container_type` and it builds a Vector
    instead (design 54 Part 4).

    A REPEAT literal sets `repeat_count` and holds its single value in
    `elements[0]`. Keeping it on this node rather than minting a second one is
    what it is — an array literal whose elements are all the same — and it means
    every walker that already visits `elements` keeps visiting the value with no
    change. The count is a compile-time constant, so it contains no call and no
    suspension and needs no walker of its own."""
    elements: List[Expression]

    # Set when the expected type made this literal build a Vector rather than a
    # fixed array (design 54 Part 4 / design 126 R1).
    vector_container_type: Optional['SawType'] = annotation(None)

    # `N` in `[v; N]` (design 148): the count expression as written.
    #
    # Declared as an ANNOTATION even though the author wrote it, because the
    # classification is about what WALKERS should do with a field, and this one
    # is compile-time-only: it never lowers to an instruction, so the coroutine
    # transform's hoist must not lift it into a `let` (that would turn a
    # constant into a runtime binding and the count would stop being constant on
    # the post-transform re-check). `substitute_ast_types` still visits it,
    # which is what a `[v; N]` inside a generic body needs.
    repeat_count: Optional[Expression] = annotation(None)


@dataclass
class MapLiteral(Expression):
    """Map literal `{k1: v1, k2: v2}` and the empty map `{:}` (design 54).

    Lowers to a Map construction + one insert per entry, in source order
    (duplicate keys: last wins). `{:}` (no entries) requires an expected type."""
    entries: List[tuple]  # [(key_expr, value_expr), ...]


@dataclass
class SetLiteral(Expression):
    """Set literal `{a, b, ...}` (design 54, two or more elements — the comma
    disambiguates it from a `{expr}` closure/block).

    Lowers to a Set construction + one insert per element, in source order."""
    elements: List[Expression]


@dataclass
class ArrayIndex(Expression):
    """Array indexing: arr[i]"""
    array_expr: Expression
    index: Expression  # Can be any expression that evaluates to Int

    # Projection into an UnsafeMemory register block (design 112, R1).
    um_projection: bool = annotation(False)

    # A PLACE use (design 141/146): this index resolved to a `[]` borrows
    # accessor, so it names storage rather than producing a value. The checker
    # stamps these and `place_uses.py` turns the node into the window call.
    # `place_elem_type` is a real type and must be substituted along with every
    # other one when a generic body is monomorphized, which is why it is a
    # declared annotation rather than a runtime graft.
    place_struct: Optional[str] = annotation(None)
    place_method: Optional[str] = annotation(None)
    place_elem_type: Optional['SawType'] = annotation(None)
    place_optional: bool = annotation(False)


@dataclass
class MemberAccess(Expression):
    """Access a member/field of an expression."""
    object: Expression
    member: str

    # --- typechecker -> codegen (design 126 R1) ---
    # A qualified access `mod.name` that resolved through a module.
    resolved_module: Optional[str] = annotation(None)
    resolved_module_symbol: Optional[Any] = annotation(None)
    resolved_static_name: Optional[str] = annotation(None)
    resolved_struct_name: Optional[str] = annotation(None)
    # `.0` / `.x` on a tuple: the positional index it projects.
    tuple_field_index: Optional[int] = annotation(None)
    # A builtin integer bound (`Int.max`): (type name, member).
    int_limit: Optional[tuple] = annotation(None)
    # A raw-backed enum CASE (`SysOp.Shutdown`): the tag value it denotes
    # (design 145 unit B2). Stamped only when the enum declared a backing, which
    # is exactly when the value is part of the type rather than an ordinal the
    # compiler may renumber — so this is the constant a `static_assert` may
    # read, and an unbacked enum's case stays non-constant.
    enum_raw_value: Optional[int] = annotation(None)
    # The QUALIFIED spelling of DF-172j's stamps: `dep.REGION_SIZE` in a
    # constant. Same two halves and same reader as the `Identifier` pair — the
    # bare and qualified spellings of one name have to fold to one number, which
    # is what DF-172l filed (design 185 unit 2 gave the type position a grammar
    # that reaches the member access; this is the resolution behind it).
    const_static_value: Optional[int] = annotation(None)
    const_static_reject: Optional[str] = annotation(None)
    # Projection into an UnsafeMemory register block (design 112).
    um_projection: bool = annotation(False)


@dataclass
class StructInit(Expression):
    """Struct initialization: Point(x: 10, y: 20) or Box<Int>(value: 42)"""
    struct_name: str
    field_inits: List[tuple[str, Expression]]  # [(field_name, value), ...]
    type_args: Optional[List['SawType']] = None  # For generic structs: Box<Int> has type_args=[Int]
    # Resolution metadata (filled in by type checker)
    resolved_init_params: Optional[List[str]] = None  # None = field init, List = custom init params
    # The literal actually resolved to a custom `init`, i.e. a call (design 126 R1).
    as_function_call: Optional['FunctionCall'] = annotation(None)


@dataclass
class NoneLiteral(Expression):
    """The None literal for optionals."""
    pass


@dataclass
class SourceLocationLiteral(Expression):
    """A `#file` / `#line` / `#function` source-location magic literal (design 98).

    Resolved at type-check time to an ordinary compile-time constant at its
    DEFINITION site (where the token appears in source): `#file` -> the source
    BASENAME (String, matching the design-69 panic prefix), `#line` -> the
    1-based token line (Int), `#function` -> the enclosing function/method bare
    name (String; module scope -> `<module>`). Zero runtime cost, freestanding-
    safe, valid in const/static/default-value positions.

    `source_file` is stamped by the parser (the file the token appears in);
    `line`/`column` are the token position (rebased into real source
    coordinates for an interpolation sub-expression, design 99). The typechecker
    (`visit_SourceLocationLiteral`) fills `resolved_kind` + the value fields
    exactly once, freezing the definition-site value so the coroutine transform
    cannot distort it; codegen emits it as a plain Int/String literal."""
    kind: str = 'file'                       # 'file' | 'line' | 'function'
    source_file: Optional[str] = None
    resolved_kind: Optional[str] = None      # 'int' | 'string' (set by typechecker)
    resolved_int: int = 0
    resolved_str: Optional[str] = None


@dataclass
class LendVarLiteral(Expression):
    """The `#lend_var` compile-time constant (design 179).

    Legal ONLY inside a `borrows` body, where it names the SPECIALIZATION being
    compiled rather than anything about the running program: `false` in the
    shared copy, `true` in the exclusive one. A body that mentions it compiles
    TWICE — `place_transform` folds the constant and prunes the branch it
    decides, so each copy reaches the type checker as an ordinary method with
    no trace of the other. A body that never mentions it compiles once, exactly
    as before.

    Nothing downstream of the place transform can see one: every LEGAL
    occurrence is folded away before checking, so the type checker's visitor is
    the scope fence and always errors."""
    pass


@dataclass
class ForceUnwrap(Expression):
    """Force unwrap: expr!

    Two marks the coroutine transform stamps on the `self.name!` reads it
    synthesizes for opt-encoded frame fields (design 124 / 131). Both say the
    frame — not the language's ordinary place rule — decides this read's
    ownership, because the transform pairs it with its own bookkeeping:
      frame_owning_read -- a non-`move` whole-binding read; the frame KEEPS the
                           field, so codegen retains at the transfer site.
      frame_move_read   -- a `move` read; the paired `__saw_forget` hands the
                           frame's own reference over, so it is a transfer even
                           for a NoCopy payload.
    """
    expr: Expression
    frame_owning_read: bool = annotation(False)
    frame_move_read: bool = annotation(False)


@dataclass
class NilCoalesce(Expression):
    """Nil coalescing: expr ?? default"""
    expr: Expression
    default: Expression


@dataclass
class OptionalChain(Expression):
    """Optional chaining: expr?.member (legacy single-hop node, no longer emitted
    by the parser — full chains lower to BindOptional / OptionalEvalExpr below).
    Kept for back-compat of imports; its visitors are unreachable."""
    expr: Expression
    member: str


@dataclass
class BindOptional(Expression):
    """An `?.` unwrap point inside an optional chain (design 111). Wraps the
    receiver expression whose Optional payload is projected on the some-path and
    short-circuits the enclosing OptionalEvalExpr to None otherwise. Types to the
    payload type U (the object of the following `.member`/`.method()` segment)."""
    expr: Expression


@dataclass
class OptionalEvalExpr(Expression):
    """The maximal postfix chain containing at least one `?.` hop (design 111).
    Its inner spine is a nest of MemberAccess/MethodCall whose optional hops are
    marked by BindOptional. Types to `U?` where U is the spine's type, flattening
    an already-optional U (never `U??`)."""
    expr: Expression


@dataclass
class OptionalChainAssign(Expression):
    """Chained assignment `x?.y = v` (design 111). `target` is an OptionalEvalExpr
    whose final segment is a payload FIELD; writes the RHS through the chain in
    place iff every optional hop is non-None. Types to `Void?` (None = skipped,
    Some(unit) = written); silently discardable in statement position."""
    target: Expression
    value: Expression


@dataclass
class OptionalWrap(Expression):
    """Wraps a value T into Optional<T> (Some).

    Inserted by typechecker when T is used where T? is expected.
    """
    value: Expression
    target_type: Optional['SawType'] = None  # The full T? type

    # Synthesized by the typechecker, so it never flows through the
    # _check_expression chokepoint: default the inherited `resolved_type` from
    # the target type so codegen still sees one.
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

    # Synthesized by the typechecker (bypasses the _check_expression
    # chokepoint); default the inherited `resolved_type` for codegen.
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

    # Synthesized by the typechecker (bypasses the _check_expression
    # chokepoint); default the inherited `resolved_type` for codegen.
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

    # --- typechecker -> codegen (design 126 R1) ---
    # The concrete Result enum this `try` unwraps.
    result_enum_type: Optional['SawType'] = annotation(None)
    # Propagating into an ERASED `Result<T, Box<any Error>>`: the boxing
    # descriptor codegen needs to erase the concrete error on the way out.
    erase_propagate: Optional[Dict[str, Any]] = annotation(None)


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

    # The catch's error type (design 30 Ruling 2). For a MULTI-error catch this
    # is the synthesized `_CatchError_<id>` union enum and `error_types` lists
    # its members (design 126 R1).
    error_type: Optional['SawType'] = annotation(None)
    error_types: Optional[List['SawType']] = annotation(None)


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

    # --- typechecker -> codegen call plan (design 126 R1) ---------------------
    # See FunctionCall.arg_plan / .resolved_symbol -- same meaning here.
    arg_plan: Optional[List[Optional[int]]] = annotation(None)
    resolved_symbol: Optional[str] = annotation(None)
    # Dispatch shape decided during checking.
    existential_dispatch: Optional[str] = annotation(None)   # trait name, for `any Trait` vtable dispatch
    is_field_call: bool = annotation(False)                  # calling a closure-typed FIELD, not a method
    field_call_unwrap: bool = annotation(False)
    array_builtin: Optional[str] = annotation(None)          # "len" | "swap" on a fixed array
    is_chan_recv: bool = annotation(False)                   # cooperative Channel.receive()
    # design 131: `o.take()` — `Optional.take(&var self) -> T?`. Swaps `None`
    # into the receiver place and returns the payload owned.
    optional_take: bool = annotation(False)
    # design 170: `UInt8.from(x)` / `UInt8.from(truncating: x)` — the conversion
    # family beside the checked cast. `(target TypeKind, is_truncating,
    # source_is_signed)`; there is no symbol to call, so codegen lowers it
    # inline from this plan. The source signedness rides along because the
    # ARGUMENT decides how the value extends, and the typechecker is the pass
    # that knows it.
    int_from: Optional[tuple] = annotation(None)
    # Auto-forwarding through a smart pointer: the payload type reached through
    # Arc<T> / Box<T> when the method lives on T rather than on the wrapper.
    arc_forward_payload_type: Optional['SawType'] = annotation(None)
    box_forward_payload_type: Optional['SawType'] = annotation(None)
    # Erased-existential operations (design 56 N3): the box/downcast descriptors
    # codegen needs. Dicts today; their shape lives at the writer sites.
    erased_box_make: Optional[Dict[str, Any]] = annotation(None)
    erased_downcast: Optional[Dict[str, Any]] = annotation(None)
    # The call turned out to be an enum-variant construction.
    resolved_enum_init: Optional['EnumInit'] = annotation(None)
    # `group.spawn(f(...))`: the spawned root's name, consumed by the coroutine
    # transform to build f's frame.
    spawn_root: Optional[str] = annotation(None)
    # --- UnsafeMemory method plan (design 81/112) ---
    um_method: Optional[str] = annotation(None)
    um_scalar_type: Optional['SawType'] = annotation(None)
    um_volatile: bool = annotation(False)
    resolved_init_params: Optional[List[str]] = annotation(None)
    # A PLACE use (design 141/146): this call resolved to a named `borrows`
    # accessor (`v.get(i)`, `v.first()`), so it names storage rather than
    # returning a value. See ArrayIndex for what each field carries.
    place_struct: Optional[str] = annotation(None)
    place_method: Optional[str] = annotation(None)
    place_elem_type: Optional['SawType'] = annotation(None)
    place_optional: bool = annotation(False)
    # Set by the use-site lowering on the call IT synthesized: this is the
    # accessor's window call, with the closures supplied, so the place path must
    # not claim it a second time on the re-check.
    place_lowered: bool = annotation(False)
    # Design 141 decision 3: mutability comes from the USE SITE, so the window
    # this call opens — not the accessor's `&self` declaration — says whether
    # the root is borrowed shared or exclusively.
    place_window_exclusive: bool = annotation(False)


@dataclass
class SelfExpr(Expression):
    """The 'self' keyword"""


@dataclass
class IfLetExpr(Expression):
    """Optional binding: if let/var x = optional { ... } else { ... }

    `pattern` (design 63) is set when the binding is a tuple pattern over an
    `(T, U)?` scrutinee (`if let (x, y) = maybe_pair`); `name` is unused then."""
    name: str
    optional_expr: Expression
    mutable: bool  # True for 'if var', False for 'if let'
    then_branch: 'Block'
    else_branch: Optional['Block'] = None
    pattern: Optional['Pattern'] = None
    # The coroutine transform CFG-split this binding across a suspension
    # (design 104 item 1 / design 126 R1).
    _coro_split: bool = annotation(False)


@dataclass
class GuardLetStatement(ASTNode):
    """Guard statement: guard let/var x = optional else { return }

    `pattern` (design 63) is set for a tuple pattern over an `(T, U)?`
    scrutinee (`guard let (x, y) = maybe_pair else { ... }`)."""
    name: str
    optional_expr: Expression
    mutable: bool  # True for 'guard var', False for 'guard let'
    else_branch: 'Block'  # Must contain early exit (return, break, etc.)
    pattern: Optional['Pattern'] = None
    # The coroutine transform CFG-split this binding across a suspension
    # (design 104 item 1 / design 126 R1).
    _coro_split: bool = annotation(False)
    # design 131: the bound payload is read out of a place the scrutinee keeps,
    # and the place rule says the binding retains it (and therefore owns it, so
    # it is released at the end of the guarded scope). See `Expression`.
    payload_needs_copy: bool = annotation(False)


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


# ===== Patterns (design 63 T1d) =====
# A Pattern is the refutable/irrefutable shape tested by a match arm (and the
# irrefutable subset by `let`/`var`/`if let`/`guard let` destructuring). The
# classic enum-variant match keeps using MatchArm.variant_name/bindings so its
# switch lowering (design 61 consume model + the coroutine CFG walk) is
# untouched; the new pattern forms flow through MatchArm.pattern instead.
@dataclass
class Pattern(ASTNode):
    pass


@dataclass
class WildcardPattern(Pattern):
    """`_` — matches anything, binds nothing."""
    pass


@dataclass
class BindingPattern(Pattern):
    """A bare lowercase identifier — matches anything, binds the whole value."""
    name: str = ""


@dataclass
class LiteralPattern(Pattern):
    """An integer / Bool / String literal pattern (`case 0`, `case "build"`,
    `case true`). `value` is the literal expression (IntLiteral / BoolLiteral /
    StringLiteral, or a UnaryOp('-', IntLiteral) for a negative literal)."""
    value: Optional['Expression'] = None


@dataclass
class RangePattern(Pattern):
    """`case 1..9` (exclusive) / `case 1..=9` (inclusive). Endpoints are
    constant integer expressions; same Int-typing rules as range expressions."""
    start: Optional['Expression'] = None
    end: Optional['Expression'] = None
    is_inclusive: bool = False


@dataclass
class TuplePattern(Pattern):
    """`case (p0, p1, ...)` — positional tuple destructuring; elements are
    themselves patterns (nested literals / ranges / bindings / enum patterns)."""
    elements: List['Pattern'] = field(default_factory=list)


@dataclass
class EnumPattern(Pattern):
    """`case Variant(sub0, sub1)` used as a nested pattern (e.g. an Optional
    component inside a tuple pattern). `subpatterns` are patterns, not just
    binding names, so `case (Some(x), 0)` composes."""
    variant_name: str = ""
    subpatterns: List['Pattern'] = field(default_factory=list)


@dataclass
class MatchArm(ASTNode):
    """Match arm: case VariantName(binding1, binding2) -> expression

    Legacy enum-variant / wildcard arms populate `variant_name` + `bindings`
    (and the switch lowering reads those). New pattern forms (literals, ranges,
    tuples, guards) populate `pattern` and optionally `guard`; the general
    if-chain lowering reads those. The parser fills both when an arm is a plain
    enum-variant/wildcard so either lowering can consume it."""
    variant_name: str
    bindings: List[str]  # Variable names to bind associated values to
    body: Expression  # Can be an expression or a Block
    pattern: Optional['Pattern'] = None
    guard: Optional['Expression'] = None

    # --- place transform -> codegen (design 146, DF-146d) ---
    # The arm's own payload bindings that a `lend` in this arm hands out as a
    # PLACE. Codegen writes each one back into the scrutinee's payload when the
    # window closes, so a write through the window reaches the enum's storage.
    lent_bindings: Optional[List[str]] = annotation(None)


@dataclass
class MatchExpr(Expression):
    """Match expression: match value { case Variant1 -> expr1, case Variant2 -> expr2 }"""
    matched_expr: Expression
    arms: List[MatchArm]

    # --- typechecker -> codegen match plan (design 126 R1) ---
    # The enum being switched on, for the classic variant lowering.
    matched_enum_type: Optional['SawType'] = annotation(None)
    # Set when the arms need the GENERAL pattern lowering (literals, ranges,
    # tuples, guards) rather than the enum-variant switch; then
    # `matched_scrutinee_type` carries the scrutinee's type.
    use_general_match: bool = annotation(False)
    matched_scrutinee_type: Optional['SawType'] = annotation(None)


@dataclass
class RangeExpr(Expression):
    """Range expression: `start..end` (exclusive) or `start..=end` (inclusive,
    design 53). An inclusive range lowers to the Int.max-safe `RangeInclusive`
    iterator, never to a `start..(end + 1)` desugar."""
    start: Expression
    end: Expression
    is_inclusive: bool = False


@dataclass
class ClosureParam:
    """A parameter in a closure expression."""
    name: str
    type_annotation: Optional[SawType] = None
    is_reference: bool = False       # True for `&data` / `&var data` params
    reference_mutable: bool = False  # True for `&var data`
    # Design 176 (DF-175b): set on the parameter of a SHARED place window that
    # `place_uses` synthesizes. Every accessor is lowered with one `(&var T)`
    # window closure — the flavor is a property of the use site, not of the
    # declaration — so the shared flavor used to receive a mutable reference and
    # soundness rested entirely on the use-site classifier being complete. The
    # binding is read-only whatever the closure's TYPE says, which turns a
    # misclassification into a compile error instead of a silent write through
    # storage the root holds immutably. No source spells this.
    place_shared_window: bool = False
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


@dataclass
class DestructuringLet(Statement):
    """`let (a, b) = pair` / `var (x, y) = point` (design 63 T1d).

    `pattern` must be irrefutable — a TuplePattern of bindings / wildcards /
    nested irrefutable tuples (per-position `_` is a discard). Destructuring
    consumes the whole source tuple (design 35 L1); each component moves out."""
    pattern: 'Pattern'
    value: Expression
    mutable: bool = False


@dataclass
class AssignStatement(Statement):
    target: Expression  # Can be Identifier or MemberAccess
    value: Expression


@dataclass
class CompoundAssignStatement(Statement):
    """Compound assignment: x += 1, y -= 2, etc."""
    target: Expression  # Can be Identifier, MemberAccess, or ArrayIndex
    op: str  # '+', '-', '*', '/', '%'
    value: Expression


@dataclass
class ReturnStatement(Statement):
    value: Optional[Expression]


@dataclass
class ExpressionStatement(Statement):
    expression: Expression


@dataclass
class LendStatement(Statement):
    """`lend <place>` — the borrow window of a `borrows` body (design 141).

    Not a return. The function PAUSES here with its frame alive, the caller's
    window code runs inside the pause, and the function then RESUMES through
    whatever follows (the epilogue) before it finishes. `place` names storage
    that already exists — a field, an element, a deref — never a temporary.

    Every path through a `borrows` body lends exactly once, returns `None`
    (only when the declared place type is optional), or diverges first; that
    coverage rule is what makes the split well defined.
    """
    place: Expression


@dataclass
class WhileExpr(Expression):
    condition: Optional[Expression]  # None for infinite loop
    body: 'Block'
    result_type: Optional['SawType'] = None  # Set by typechecker for expression context
    # design 177: does this loop DIVERGE? True for the conditionless
    # `while { ... }` whose body holds no `break` targeting it — nothing ever
    # takes the loop's exit edge, so the expression types `Never` exactly as
    # `panic(...)` does and codegen terminates the (predecessor-less) exit block
    # with `unreachable`. Stamped by whichever while-checking entry point the
    # loop went through. The `while true { ... }` spelling is deliberately
    # EXCLUDED and is never marked: it carries a condition, so it stays an
    # ordinary loop a later edit may falsify.
    diverges: bool = annotation(default=False)


@dataclass
class BreakStatement(Statement):
    value: Optional[Expression] = None  # Optional break value


@dataclass
class ContinueStatement(Statement):
    pass


@dataclass
class ForLoop(Statement):
    """For loop: for variable in iterable { body }"""
    variable: str
    iterable: Expression  # Usually a RangeExpr
    body: 'Block'
    result_type: Optional['SawType'] = None  # Set by typechecker for expression context
    element_type: Optional['SawType'] = None  # Loop-variable type (design 65: drop owning loop var per iteration)


@dataclass
class Block(ASTNode):
    statements: List[Statement]
    final_expr: Optional[Expression] = None


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
    # Member visibility (design 80): private-by-default outside the defining
    # module. `public` / `public(package)` / `public(parent)` per field.
    visibility: 'Visibility' = Visibility.PRIVATE
    line: int = 0
    column: int = 0
    # Doc comment (design 121): the `///` block immediately preceding the field,
    # markers stripped and lines joined with "\n". None when undocumented.
    doc: Optional[str] = None


@dataclass
class Struct(ASTNode):
    """Struct declaration: struct Point { x: Int, y: Int } or struct Box<T> { value: T }"""
    name: str
    fields: List[StructField]
    type_params: List['TypeParameter'] = field(default_factory=list)
    visibility: 'Visibility' = Visibility.PRIVATE
    # `unsafe struct` (design 130): this type is UNSAFE. A function that names,
    # binds, receives or returns one of its values is unsafe (rule 3). Unsafety
    # is NOT transitive — a safe struct with an unsafe FIELD stays safe, and only
    # the methods that touch the field are unsafe. The compiler requires an
    # unsafe type's name to start with `Unsafe`.
    is_unsafe: bool = False
    source_file: str = ""
    doc: Optional[str] = None
    # Design 144: the module-qualified IDENTITY the typechecker stamps here at
    # registration (`Header$m$dep`), empty when the declaring module does not
    # qualify. `name` stays the name the author wrote — diagnostics, docs and
    # the AST dump render that — while codegen keys its layout, its
    # monomorphizations and its method symbols off the identity.
    type_identity: str = ""


@dataclass
class EnumVariant:
    """A variant in an enum declaration."""
    name: str
    associated_types: List[tuple[str, SawType]]  # [(param_name, type), ...]
    doc: Optional[str] = None
    # Raw backing value (design 145 unit B2): the explicit `= <int>` a case
    # carries under a declared backing type. Required for every case when the
    # enum declares one, and absent otherwise — declaring a backing claims the
    # numbers are ABI, so nothing is auto-assigned.
    raw_value: Optional[int] = None
    # Source position of the `= <int>`, for the duplicate-value diagnostic.
    raw_line: int = 0
    raw_column: int = 0


@dataclass
class Enum(ASTNode):
    """Enum declaration: enum Status { case Success } or enum Option<T> { case Some(value: T), case None }"""
    name: str
    variants: List[EnumVariant]
    type_params: List['TypeParameter'] = field(default_factory=list)
    visibility: 'Visibility' = Visibility.PRIVATE
    source_file: str = ""
    doc: Optional[str] = None
    # Declared integer backing (design 145 unit B2): `enum SysError: UInt8`.
    # Pins the representation — width and tag values — so the enum is castable
    # to the backing with `as` and legal as a field of an `UnsafeMemory`-viewed
    # struct. Payload-free enums only.
    raw_type: Optional[SawType] = None
    # Design 144: see Struct.type_identity.
    type_identity: str = ""


@dataclass
class TraitMethod(ASTNode):
    """Method signature in a trait, optionally with a default body (design 56)."""
    name: str
    parameters: List[Parameter]  # includes self
    return_type: SawType
    self_mutable: bool = False  # True for '&var self'
    self_is_reference: bool = False  # True for '&self' or '&var self'
    is_sync: bool = False  # `func m(...) sync` — a checked suspension-free method
    is_unsafe: bool = False  # `unsafe func m(...)` — an unsafe requirement (design 130)
    # Default method body (design 56): a trait method declared WITH a `{ ... }`
    # body is a default. Conformers may omit it (the compiler synthesizes a
    # per-conformer Method from this body) or override it. None = required method.
    body: Optional['Block'] = None
    doc: Optional[str] = None


@dataclass
class AssociatedType(ASTNode):
    """Associated type declaration in a trait: type Item"""
    name: str
    bounds: List[str] = field(default_factory=list)  # Trait bounds (future)


@dataclass
class Trait(ASTNode):
    """Trait declaration: trait ImplicitCopy: Deinit { func copy(self) -> Self }"""
    name: str
    methods: List[TraitMethod]  # Required method signatures
    associated_types: List[AssociatedType] = field(default_factory=list)
    type_params: List[TypeParameter] = field(default_factory=list)
    parent_traits: List[str] = field(default_factory=list)  # Inherited traits
    visibility: 'Visibility' = Visibility.PRIVATE
    source_file: str = ""
    doc: Optional[str] = None
    # Design 144: see Struct.type_identity.
    type_identity: str = ""


@dataclass
class TypeAssignment(ASTNode):
    """Type assignment in an extension: type Item = Int"""
    name: str  # Associated type name
    assigned_type: 'SawType'  # The concrete type


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
    source_file: str = ""
    doc: Optional[str] = None
    # Declaration attributes (design 58 machinery, design 128): `@synthesize`.
    attributes: List['Attribute'] = field(default_factory=list)
    # Design 144: the IDENTITY of the type this extension extends — the
    # receiver every method here mangles against. `struct_name` stays the name
    # the author wrote.
    type_identity: str = ""


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
    # Compiler-derived serialization (design 169). Unlike the four above, these
    # two carry a real synthesized BODY (built in typechecker/serde.py once every
    # type is registered) rather than an empty block codegen fills from the
    # layout, so they are typechecked and lowered like any hand-written method.
    is_derived_serialize: bool = False
    is_derived_deserialize: bool = False
    is_sync: bool = False  # True for a `sync func` method (checked suspension-free)
    # `unsafe func` / `unsafe init` (design 130): this method touches an unsafe
    # type. Declared, never inferred — the trigger rule checks the declaration
    # against the body rather than supplying it.
    is_unsafe: bool = False
    # `borrows` (design 141): this method yields a PLACE of `return_type` for a
    # window rather than a value. Its body lends exactly once per path; the
    # place transform rewrites it into the window-closure form and records the
    # lent type in `place_type`, leaving this bit set as the declaration's own
    # record of what the author wrote.
    is_borrows: bool = False
    # Set by the place transform (design 141) on a rewritten borrows method: the
    # type of the place it lends, i.e. the `T` the author wrote after `->`
    # (unwrapped from `T?` for a conditional lend, with `place_optional` set).
    # Cross-pass ANNOTATIONS, not structure: `place_type` aliases a type node
    # that also hangs off the rewritten `__window` parameter, so a child walker
    # that followed it would visit the same subtree twice.
    place_type: Optional['SawType'] = annotation(None)
    place_optional: bool = annotation(False)
    # Set with `place_type` on a lowered borrows METHOD: its receiver travels as
    # a POINTER even when the author wrote `&self`, because the window may write
    # through it (design 146, DF-146b). See `self_by_pointer`.
    place_self_by_pointer: bool = annotation(False)
    # `#lend_var` (design 179). `place_lend_var` marks the AUTHORED declaration
    # whose body named the constant — it is the SHARED specialization, folded
    # with the constant false. `place_var_twin` marks the synthesized exclusive
    # sibling: same body folded true, `self_mutable` set, a reserved name no
    # author could write. The twin is an implementation detail of one authored
    # accessor, so `--emit-docs` skips it and every diagnostic names the
    # original.
    place_lend_var: bool = annotation(False)
    place_var_twin: bool = annotation(False)
    # Method-level generic type params (brief 36): the `U` in `func map<U>(...)`,
    # distinct from and in addition to the enclosing extension's own type params.
    type_params: List['TypeParameter'] = field(default_factory=list)
    # Member visibility (design 80): private-by-default outside the defining
    # module, for extension methods (incl. init + static). A method satisfying a
    # trait requirement is callable wherever the conformance is visible regardless.
    visibility: 'Visibility' = Visibility.PRIVATE
    # Compiler-synthesized (design 80): coroutine-transform-generated methods
    # (frame `resume`/`__wake_reason`) are exempt from the member-visibility gate.
    is_synthesized: bool = False
    source_file: str = ""
    doc: Optional[str] = None
    # The per-overload / per-instantiation codegen symbol, stamped by
    # registration once overloads are numbered; None means "use `name`"
    # (design 126 R1).
    mangled_symbol: Optional[str] = annotation(None)


@dataclass
class Attribute(ASTNode):
    """A Swift-style declaration attribute (design 58): `@name` or `@name("arg")`.

    Attached to the declaration immediately following it. The legal names are
    `export` and `section` (on a top-level func/static) and `synthesize` (on an
    extension, design 128); `export` takes zero args or one string literal,
    `section` requires exactly one string literal, `synthesize` takes none.
    `arg` is the decoded string literal content (no quotes), or None for the
    bare `@name` form.
    """
    name: str
    arg: Optional[str] = None


# Known attribute names. Used for the unknown-name diagnostic.
KNOWN_ATTRIBUTES = ("export", "section", "synthesize")

# Where each attribute may appear. The parser enforces this (position is a
# grammar property); the typechecker owns the per-attribute semantics.
FUNC_STATIC_ATTRIBUTES = ("export", "section")
EXTENSION_ATTRIBUTES = ("synthesize",)


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


def has_synthesize(node: 'ASTNode') -> bool:
    """True if `node` carries the `@synthesize` attribute (design 128): the
    author's explicit buy-in to a compiler-derived conformance body."""
    return find_attribute(node, 'synthesize') is not None


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
    # `unsafe func` declaration (design 130): see Method.is_unsafe.
    is_unsafe: bool = False
    # `borrows func` declaration (design 141): see Method.is_borrows.
    is_borrows: bool = False
    place_type: Optional[SawType] = annotation(None)
    place_optional: bool = annotation(False)
    # Declaration attributes (design 58): `@export` / `@section(...)` lines.
    attributes: List['Attribute'] = field(default_factory=list)
    # Compiler-synthesized (design 80): coroutine-transform-generated functions
    # (spawn/drive wrappers, synthesized main) access std internals by
    # construction, so their member access is EXEMPT from the visibility gate —
    # the gate enforces source-level access only.
    is_synthesized: bool = False
    source_file: str = ""
    doc: Optional[str] = None
    # See Method.mangled_symbol (design 126 R1).
    mangled_symbol: Optional[str] = annotation(None)


@dataclass
class TypeDefinition(ASTNode):
    """Type definition: type MyInt = Int"""
    name: str
    defined_type: 'SawType'
    visibility: 'Visibility' = Visibility.PRIVATE
    source_file: str = ""
    doc: Optional[str] = None
    # Design 144: see Struct.type_identity.
    type_identity: str = ""


@dataclass
class StaticDecl(ASTNode):
    """Module-level static declaration: static NAME: Type = initializer (design 41).

    Statics are const-initialized and immortal (never deinit). An immutable one
    is Sync-only — global mutation flows through interior-synchronized types
    (`Atomic<Int>`, and since design 149 `SpinLock<T>`), which is still the
    recommendation for single-word state several tasks update independently.

    `unsafe static var` (design 149 unit a) is the compound case Atomics cannot
    express: a handle table of multi-word slots, a bitmap paired with the queues
    it indexes, an arena's backing storage. Its consistency comes from a
    serialization argument the compiler cannot see (interrupts off, single core,
    boot only), so the declaration is `unsafe` and the trigger rule makes every
    function that NAMES it say `unsafe` too — which is what puts the argument in
    front of a reviewer. `is_var` and `is_unsafe` are set together; the parser
    rejects either half alone.

    `initializer` is None for a bare zero-init declaration
    (`static BUF: [Int8; 4096]`), which is only permitted for zero-initable
    types.
    """
    name: str
    type: 'SawType'
    initializer: Optional['Expression'] = None
    visibility: 'Visibility' = Visibility.PRIVATE
    # design 149: `unsafe static var` — a MUTABLE static. Always set together.
    is_var: bool = False
    is_unsafe: bool = False
    # Declaration attributes (design 58): `@export` / `@section(...)` lines.
    attributes: List['Attribute'] = field(default_factory=list)
    source_file: str = ""
    doc: Optional[str] = None


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


@dataclass
class ExternBlock(ASTNode):
    """extern "C" { ... } block for FFI declarations."""
    abi: str  # "C" for now
    functions: List[ExternFunction]


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
    # Module doc comment (design 121): the `//!` block(s) at the top of the file,
    # markers stripped and lines joined with "\n". None when undocumented.
    module_doc: Optional[str] = None

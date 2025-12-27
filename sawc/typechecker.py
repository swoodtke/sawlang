"""
Saw Language Type Checker
Performs type checking and semantic analysis on the AST.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from ast_nodes import (
    Program, Function, Block, Statement, Expression,
    LetStatement, AssignStatement, ReturnStatement, ExpressionStatement,
    WhileExpr, BreakStatement, ContinueStatement, ForLoop, RangeExpr,
    IntLiteral, FloatLiteral, BoolLiteral, StringLiteral, Identifier,
    BinaryOp, UnaryOp, MoveExpr, CastExpr, FunctionCall, IfExpr, IfLetExpr,
    TupleLiteral, TupleIndex, ArrayLiteral, ArrayIndex,
    MemberAccess, StructInit,
    NoneLiteral, ForceUnwrap, NilCoalesce, OptionalChain,
    GuardLetStatement,
    Struct, StructField,
    Enum, EnumVariant, EnumInit, MatchExpr, MatchArm,
    Extension, Method, MethodCall, SelfExpr,
    Interface, InterfaceMethod, AssociatedType, TypeAssignment, TypeDefinition,
    ExternFunction, ExternBlock,
    SawType, TypeKind, Parameter, Argument, TypeParameter,
    ClosureExpr, ClosureParam
)
from errors import ErrorReporter, ErrorKind


@dataclass
class VariableInfo:
    """Information about a variable in scope."""
    type: SawType
    mutable: bool
    line: int
    column: int


@dataclass
class FunctionInfo:
    """Information about a function."""
    param_types: List[SawType]
    return_type: SawType
    param_names: List[str]
    type_params: List[TypeParameter] = field(default_factory=list)  # For generic functions


@dataclass
class StructInfo:
    """Information about a struct."""
    name: str
    fields: Dict[str, SawType]  # field_name -> type
    field_order: List[str]  # preserve declaration order
    line: int = 0
    column: int = 0
    methods: Dict[str, 'MethodInfo'] = field(default_factory=dict)  # method_name -> info
    type_params: List[TypeParameter] = field(default_factory=list)  # For generic structs


@dataclass
class EnumInfo:
    """Information about an enum."""
    name: str
    variants: Dict[str, List[Tuple[str, SawType]]]  # variant_name -> [(param_name, type), ...]
    variant_order: List[str]  # preserve declaration order
    type_params: List[TypeParameter] = field(default_factory=list)  # For generic enums


@dataclass
class MethodInfo:
    """Information about a method."""
    struct_name: str
    method_name: str
    param_types: List[SawType]  # Includes self for instance methods
    return_type: SawType
    param_names: List[str]
    self_mutable: bool  # True if 'var self'
    is_init: bool = False


@dataclass
class InterfaceMethodInfo:
    """Information about a method signature in an interface."""
    name: str
    param_types: List[SawType]  # Includes self
    return_type: SawType
    param_names: List[str]
    self_mutable: bool = False  # True if 'var self'


@dataclass
class InterfaceInfo:
    """Information about an interface."""
    name: str
    methods: Dict[str, InterfaceMethodInfo]  # method_name -> info
    associated_types: List[str] = field(default_factory=list)  # Associated type names (e.g., ["Item"])
    parent_interfaces: List[str] = field(default_factory=list)  # Parent interface names


class Scope:
    """A lexical scope containing variable bindings."""

    def __init__(self, parent: Optional['Scope'] = None):
        self.parent = parent
        self.variables: Dict[str, VariableInfo] = {}

    def define(self, name: str, info: VariableInfo) -> bool:
        """Define a variable in this scope. Returns False if already defined."""
        if name in self.variables:
            return False
        self.variables[name] = info
        return True

    def lookup(self, name: str) -> Optional[VariableInfo]:
        """Look up a variable, checking parent scopes."""
        if name in self.variables:
            return self.variables[name]
        if self.parent:
            return self.parent.lookup(name)
        return None

    def lookup_local(self, name: str) -> Optional[VariableInfo]:
        """Look up a variable only in this scope."""
        return self.variables.get(name)


class TypeChecker:
    """Type checks a Saw program."""

    def __init__(self, reporter: ErrorReporter):
        self.reporter = reporter
        self.structs: Dict[str, StructInfo] = {}
        self.enums: Dict[str, EnumInfo] = {}
        self.interfaces: Dict[str, InterfaceInfo] = {}
        self.functions: Dict[str, FunctionInfo] = {}
        self.current_scope: Scope = Scope()
        self.current_function: Optional[Function] = None
        self.current_method: Optional['Method'] = None  # Track current method for 'self'
        # Track return statements found in current function
        self.found_return_with_value: bool = False
        # Track loop nesting depth for break/continue validation
        self.loop_depth: int = 0
        # Track break value types for each loop level
        # Each entry is (expected_type: Optional[SawType], is_infinite: bool, has_break: bool)
        self.loop_break_info: List[Tuple[Optional[SawType], bool, bool]] = []
        # Track which types implement which interfaces
        self.type_conformances: Dict[str, List[str]] = {}  # type_name -> [interface_names]
        # Track associated type assignments: (type_name, interface_name) -> {assoc_type_name: SawType}
        self.type_assignments: Dict[Tuple[str, str], Dict[str, SawType]] = {}
        # Type aliases: name -> SawType
        self.type_aliases: Dict[str, SawType] = {}
        # Track moved variables for use-after-move detection
        self.moved_variables: set[str] = set()

        # Register built-in functions
        self._register_builtins()

    def _register_builtins(self):
        """Register built-in functions."""
        # print can take any single argument
        # We'll handle it specially in check_function_call
        #
        # Note: Built-in interfaces (Deinit, CustomCopy, NoCopy) are defined
        # in builtin.saw and loaded automatically by the compiler.
        pass

    def _block_has_early_exit(self, block: Block) -> bool:
        """Check if a block definitely exits early (return, break, continue).

        This checks if the block cannot fall through to the next statement.
        A block has an early exit if:
        - It contains a return/break/continue at the top level
        - It ends with an if-else where both branches have early exits
        """
        for stmt in block.statements:
            if isinstance(stmt, (ReturnStatement, BreakStatement, ContinueStatement)):
                return True
            # Check if-else: both branches must have early exits
            if isinstance(stmt, IfExpr) and stmt.else_branch:
                then_exits = self._block_has_early_exit(stmt.then_branch)
                else_exits = self._block_has_early_exit(stmt.else_branch)
                if then_exits and else_exits:
                    return True
        return False

    def _register_type_definition(self, type_def: TypeDefinition):
        """Register a type definition (type alias)."""
        if type_def.name in self.type_aliases:
            self.reporter.error(
                ErrorKind.DUPLICATE_FUNCTION,
                f"type `{type_def.name}` is defined multiple times",
                type_def.line, type_def.column
            )
            return

        # Resolve the defined type (it might reference other type aliases)
        resolved_type = self._resolve_type_alias(type_def.defined_type)
        self.type_aliases[type_def.name] = resolved_type

    def _resolve_type_alias(self, saw_type: SawType) -> SawType:
        """Resolve any type aliases in a SawType."""
        if saw_type.kind == TypeKind.STRUCT:
            # Check if this is actually a type alias
            if saw_type.struct_name in self.type_aliases:
                return self.type_aliases[saw_type.struct_name]
            # Recursively resolve type_args
            if saw_type.type_args:
                resolved_args = [self._resolve_type_alias(t) for t in saw_type.type_args]
                return SawType(TypeKind.STRUCT, struct_name=saw_type.struct_name, type_args=resolved_args)
            return saw_type
        elif saw_type.kind == TypeKind.OPTIONAL:
            if saw_type.inner_type:
                resolved_inner = self._resolve_type_alias(saw_type.inner_type)
                return SawType(TypeKind.OPTIONAL, inner_type=resolved_inner)
            return saw_type
        elif saw_type.kind == TypeKind.TUPLE:
            if saw_type.element_types:
                resolved_elems = [self._resolve_type_alias(t) for t in saw_type.element_types]
                return SawType(TypeKind.TUPLE, element_types=resolved_elems)
            return saw_type
        elif saw_type.kind == TypeKind.ENUM:
            if saw_type.type_args:
                resolved_args = [self._resolve_type_alias(t) for t in saw_type.type_args]
                return SawType(TypeKind.ENUM, enum_name=saw_type.enum_name, type_args=resolved_args)
            return saw_type
        else:
            return saw_type

    def _is_no_copy_type(self, saw_type: SawType) -> bool:
        """Check if a type implements NoCopy (cannot be copied)."""
        if saw_type is None:
            return False

        # Get the type name for conformance lookup
        type_name = None
        if saw_type.kind == TypeKind.STRUCT:
            type_name = saw_type.struct_name
        elif saw_type.kind == TypeKind.ENUM:
            type_name = saw_type.enum_name

        if type_name is None:
            return False

        # Check if type conforms to NoCopy
        conformances = self.type_conformances.get(type_name, [])
        return "NoCopy" in conformances

    def _check_integer_literal_range(self, literal: IntLiteral, target_type: SawType):
        """Check if an integer literal fits in the target fixed-width integer type."""
        # Define ranges for each fixed-width integer type
        ranges = {
            TypeKind.INT8: (-128, 127),
            TypeKind.INT16: (-32768, 32767),
            TypeKind.INT32: (-2147483648, 2147483647),
            TypeKind.INT64: (-9223372036854775808, 9223372036854775807),
            TypeKind.UINT8: (0, 255),
            TypeKind.UINT16: (0, 65535),
            TypeKind.UINT32: (0, 4294967295),
            TypeKind.UINT64: (0, 18446744073709551615),
        }

        if target_type.kind not in ranges:
            return  # Not a fixed-width type, no range check needed

        min_val, max_val = ranges[target_type.kind]
        if literal.value < min_val or literal.value > max_val:
            type_name = target_type.kind.name
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"integer literal {literal.value} out of range for {type_name} ({min_val} to {max_val})",
                literal.line, literal.column
            )

    def _is_custom_copy_type(self, saw_type: SawType) -> bool:
        """Check if a type implements CustomCopy."""
        if saw_type is None:
            return False

        # Get the type name for conformance lookup
        type_name = None
        if saw_type.kind == TypeKind.STRUCT:
            type_name = saw_type.struct_name
        elif saw_type.kind == TypeKind.ENUM:
            type_name = saw_type.enum_name

        if type_name is None:
            return False

        # Check if type conforms to CustomCopy
        conformances = self.type_conformances.get(type_name, [])
        return "CustomCopy" in conformances

    def _is_deinit_type(self, saw_type: SawType) -> bool:
        """Check if a type implements Deinit (directly or through NoCopy/CustomCopy)."""
        if saw_type is None:
            return False

        # Get the type name for conformance lookup
        type_name = None
        if saw_type.kind == TypeKind.STRUCT:
            type_name = saw_type.struct_name
        elif saw_type.kind == TypeKind.ENUM:
            type_name = saw_type.enum_name

        if type_name is None:
            return False

        # Check if type conforms to Deinit (directly or via NoCopy/CustomCopy)
        conformances = self.type_conformances.get(type_name, [])
        # NoCopy and CustomCopy both inherit from Deinit
        return "Deinit" in conformances or "NoCopy" in conformances or "CustomCopy" in conformances

    def _check_no_copy_containment(self):
        """Check that structs containing NoCopy fields also implement NoCopy."""
        for struct_name, struct_info in self.structs.items():
            # Skip if struct already implements NoCopy
            if struct_name in self.type_conformances:
                if "NoCopy" in self.type_conformances[struct_name]:
                    continue

            # Check each field
            for field_name, field_type in struct_info.fields.items():
                if self._is_no_copy_type(field_type):
                    self.reporter.error(
                        ErrorKind.CANNOT_COPY,
                        f"struct `{struct_name}` contains NoCopy field `{field_name}` of type `{field_type}` but does not implement NoCopy",
                        struct_info.line, struct_info.column,
                        hint=f"add `extension {struct_name}: NoCopy {{ func deinit(var self) {{ ... }} }}`"
                    )
                    break  # Only report once per struct

    def _check_custom_copy_containment(self):
        """Check that structs containing CustomCopy fields also implement CustomCopy."""
        for struct_name, struct_info in self.structs.items():
            # Skip if struct already implements CustomCopy or NoCopy
            # (NoCopy types can contain CustomCopy fields since they can't be copied anyway)
            if struct_name in self.type_conformances:
                conformances = self.type_conformances[struct_name]
                if "CustomCopy" in conformances or "NoCopy" in conformances:
                    continue

            # Check each field
            for field_name, field_type in struct_info.fields.items():
                if self._is_custom_copy_type(field_type):
                    self.reporter.error(
                        ErrorKind.CANNOT_COPY,
                        f"struct `{struct_name}` contains CustomCopy field `{field_name}` of type `{field_type}` but does not implement CustomCopy",
                        struct_info.line, struct_info.column,
                        hint=f"add `extension {struct_name}: CustomCopy {{ func copy(self) -> {struct_name} {{ ... }} }}`"
                    )
                    break  # Only report once per struct

    def _check_deinit_containment(self):
        """Check that structs containing Deinit fields also implement Deinit."""
        for struct_name, struct_info in self.structs.items():
            # Skip if struct already implements Deinit (or NoCopy/CustomCopy which imply Deinit)
            if struct_name in self.type_conformances:
                conformances = self.type_conformances[struct_name]
                if "Deinit" in conformances or "NoCopy" in conformances or "CustomCopy" in conformances:
                    continue

            # Check each field
            for field_name, field_type in struct_info.fields.items():
                if self._is_deinit_type(field_type):
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"struct `{struct_name}` contains Deinit field `{field_name}` of type `{field_type}` but does not implement Deinit",
                        struct_info.line, struct_info.column,
                        hint=f"add `extension {struct_name}: Deinit {{ func deinit(var self) {{ ... }} }}`"
                    )
                    break  # Only report once per struct

    def check(self, program: Program) -> bool:
        """Type check the entire program. Returns True if no errors."""
        # First pass: register type definitions (aliases)
        for type_def in program.type_definitions:
            self._register_type_definition(type_def)

        # Second pass: collect struct definitions
        for struct in program.structs:
            self._register_struct(struct)

        # Third pass: collect enum definitions
        for enum in program.enums:
            self._register_enum(enum)

        # Fourth pass: collect interface definitions
        for interface in program.interfaces:
            self._register_interface(interface)

        # Fifth pass: register extensions and their methods
        for extension in program.extensions:
            self._register_extension(extension)

        # Fifth-b pass: check resource management containment rules
        self._check_no_copy_containment()
        self._check_custom_copy_containment()
        self._check_deinit_containment()

        # Register extern functions (FFI)
        for extern_block in program.extern_blocks:
            for extern_func in extern_block.functions:
                self._register_extern_function(extern_func)

        # Sixth pass: collect function signatures
        for func in program.functions:
            self._register_function(func)

        # Check for main function
        if "main" not in self.functions:
            self.reporter.error(
                ErrorKind.UNDEFINED_FUNCTION,
                "no `main` function found",
                1, 1,
                hint="add a `fn main() { }` function as the entry point"
            )

        # Seventh pass: type check function bodies
        for func in program.functions:
            self._check_function(func)

        # Eighth pass: type check method bodies
        for extension in program.extensions:
            self._check_extension(extension)

        return not self.reporter.has_errors()

    def _register_struct(self, struct: Struct):
        """Register a struct definition."""
        if struct.name in self.structs:
            self.reporter.error(
                ErrorKind.DUPLICATE_FUNCTION,  # We can reuse this error kind
                f"struct `{struct.name}` is defined multiple times",
                struct.line, struct.column
            )
            return

        # Check for duplicate fields
        fields = {}
        field_order = []
        seen_fields = set()

        for field in struct.fields:
            if field.name in seen_fields:
                self.reporter.error(
                    ErrorKind.DUPLICATE_VARIABLE,  # Reuse this
                    f"field `{field.name}` is defined multiple times in struct `{struct.name}`",
                    struct.line, struct.column
                )
            else:
                seen_fields.add(field.name)
                fields[field.name] = field.type
                field_order.append(field.name)

        self.structs[struct.name] = StructInfo(
            name=struct.name,
            fields=fields,
            field_order=field_order,
            line=struct.line,
            column=struct.column,
            type_params=struct.type_params
        )

    def _register_enum(self, enum: Enum):
        """Register an enum definition."""
        if enum.name in self.enums:
            self.reporter.error(
                ErrorKind.DUPLICATE_FUNCTION,  # Reuse this error kind
                f"enum `{enum.name}` is defined multiple times",
                enum.line, enum.column
            )
            return

        if enum.name in self.structs:
            self.reporter.error(
                ErrorKind.DUPLICATE_FUNCTION,
                f"enum `{enum.name}` conflicts with existing struct name",
                enum.line, enum.column
            )
            return

        # Check for duplicate variants
        variants = {}
        variant_order = []
        seen_variants = set()

        for variant in enum.variants:
            if variant.name in seen_variants:
                self.reporter.error(
                    ErrorKind.DUPLICATE_VARIABLE,  # Reuse this
                    f"variant `{variant.name}` is defined multiple times in enum `{enum.name}`",
                    enum.line, enum.column
                )
            else:
                seen_variants.add(variant.name)
                variants[variant.name] = variant.associated_types
                variant_order.append(variant.name)

        self.enums[enum.name] = EnumInfo(
            name=enum.name,
            variants=variants,
            variant_order=variant_order,
            type_params=enum.type_params
        )

    def _register_interface(self, interface: Interface):
        """Register an interface definition with inheritance support."""
        if interface.name in self.interfaces:
            self.reporter.error(
                ErrorKind.DUPLICATE_FUNCTION,
                f"interface `{interface.name}` is defined multiple times",
                interface.line, interface.column
            )
            return

        # Validate and collect inherited methods from parent interfaces
        inherited_methods = {}
        inherited_assoc_types = []
        for parent_name in interface.parent_interfaces:
            if parent_name not in self.interfaces:
                self.reporter.error(
                    ErrorKind.UNDEFINED_VARIABLE,
                    f"unknown parent interface `{parent_name}`",
                    interface.line, interface.column
                )
                continue
            parent_info = self.interfaces[parent_name]
            # Inherit all methods from parent
            for method_name, method_info in parent_info.methods.items():
                inherited_methods[method_name] = method_info
            # Inherit associated types
            for assoc_type in parent_info.associated_types:
                if assoc_type not in inherited_assoc_types:
                    inherited_assoc_types.append(assoc_type)

        # Build method info map from this interface's own methods
        methods = dict(inherited_methods)  # Start with inherited
        for method in interface.methods:
            # Collect parameter info (excluding self placeholder type)
            param_names = []
            param_types = []

            for param in method.parameters:
                if param.name == "self":
                    # self has the type of the implementing type (handled during conformance)
                    param_types.append(SawType(TypeKind.VOID))  # Placeholder
                else:
                    param_names.append(param.name)
                    param_types.append(param.type)

            methods[method.name] = InterfaceMethodInfo(
                name=method.name,
                param_types=param_types,
                return_type=method.return_type,
                param_names=param_names,
                self_mutable=method.self_mutable
            )

        # Collect associated type names (own + inherited)
        assoc_type_names = list(inherited_assoc_types)
        for at in interface.associated_types:
            if at.name not in assoc_type_names:
                assoc_type_names.append(at.name)

        self.interfaces[interface.name] = InterfaceInfo(
            name=interface.name,
            methods=methods,
            associated_types=assoc_type_names,
            parent_interfaces=interface.parent_interfaces
        )

    def _register_function(self, func: Function):
        """Register a function signature."""
        if func.name in self.functions:
            self.reporter.error(
                ErrorKind.DUPLICATE_FUNCTION,
                f"function `{func.name}` is defined multiple times",
                func.line, func.column
            )
            return

        # For generic functions, don't resolve types yet (they may contain type params)
        if func.type_params:
            param_types = [p.type for p in func.parameters]
            param_names = [p.name for p in func.parameters]
            info = FunctionInfo(param_types, func.return_type, param_names, func.type_params)
        else:
            # Resolve types before registering
            param_types = [self._resolve_type(p.type) for p in func.parameters]
            param_names = [p.name for p in func.parameters]
            resolved_return_type = self._resolve_type(func.return_type)
            info = FunctionInfo(param_types, resolved_return_type, param_names)
        self.functions[func.name] = info

    def _register_extern_function(self, extern_func: ExternFunction):
        """Register an external (FFI) function signature."""
        # Resolve types for extern functions
        param_types = [self._resolve_type(p.type) for p in extern_func.parameters]
        param_names = [p.name for p in extern_func.parameters]
        resolved_return_type = self._resolve_type(extern_func.return_type)
        info = FunctionInfo(param_types, resolved_return_type, param_names)

        if extern_func.name in self.functions:
            # Allow duplicate extern declarations with the same signature
            # This enables library code (like std/) to declare externs that
            # user code may also declare
            existing = self.functions[extern_func.name]
            if (existing.param_types == param_types and
                existing.return_type == resolved_return_type):
                return  # Same signature, allow it
            self.reporter.error(
                ErrorKind.DUPLICATE_FUNCTION,
                f"function `{extern_func.name}` is defined multiple times with different signatures",
                extern_func.line, extern_func.column
            )
            return

        self.functions[extern_func.name] = info

    def _register_extension(self, extension: Extension):
        """Register methods from an extension."""
        # Verify the struct exists
        if extension.struct_name not in self.structs:
            self.reporter.error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"cannot extend undefined struct `{extension.struct_name}`",
                extension.line, extension.column
            )
            return

        struct_info = self.structs[extension.struct_name]

        for method in extension.methods:
            # For init methods, allow multiple with different parameter signatures
            # Use parameter names in the key to distinguish them
            if method.is_init:
                param_names = tuple(p.name for p in method.parameters)
                method_key = f"init:{','.join(param_names)}"
            else:
                method_key = method.name

            # Check for duplicate methods
            if method_key in struct_info.methods:
                if method.is_init:
                    self.reporter.error(
                        ErrorKind.DUPLICATE_FUNCTION,
                        f"init method with parameters ({', '.join(p.name for p in method.parameters)}) is already defined for struct `{extension.struct_name}`",
                        method.line, method.column
                    )
                else:
                    self.reporter.error(
                        ErrorKind.DUPLICATE_FUNCTION,
                        f"method `{method.name}` is already defined for struct `{extension.struct_name}`",
                        method.line, method.column
                    )
                continue

            # For instance methods (not init), validate 'self' parameter
            self_mutable = False
            if not method.is_init:
                if len(method.parameters) == 0:
                    self.reporter.error(
                        ErrorKind.WRONG_ARGUMENT_COUNT,
                        f"method `{method.name}` must have 'self' as first parameter",
                        method.line, method.column
                    )
                    continue

                first_param = method.parameters[0]
                if first_param.name != "self":
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"first parameter of method must be named 'self', got `{first_param.name}`",
                        method.line, method.column
                    )
                    continue

                # Get self mutability from the method's AST node
                self_mutable = method.self_mutable

                # Fill in the self parameter type (if it's the placeholder VOID from parser)
                expected_self_type = SawType(TypeKind.STRUCT, struct_name=extension.struct_name)
                if first_param.type.kind == TypeKind.VOID:
                    # Replace placeholder with actual type
                    first_param.type = expected_self_type
                elif not self._types_compatible(first_param.type, expected_self_type):
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"'self' parameter must have type `{extension.struct_name}`, got `{first_param.type}`",
                        method.line, method.column
                    )

            # For init methods, check parameter names don't conflict with field names
            if method.is_init:
                param_names_set = {p.name for p in method.parameters}
                field_names_set = set(struct_info.fields.keys())
                if param_names_set == field_names_set:
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"init method parameters match field names exactly - this is ambiguous with field initialization",
                        method.line, method.column,
                        hint="use different parameter names to distinguish from field init"
                    )

            # Register method
            param_types = [p.type for p in method.parameters]
            param_names = [p.name for p in method.parameters]

            # For init methods, override return type to be the struct type
            return_type = method.return_type
            if method.is_init:
                return_type = SawType(TypeKind.STRUCT, struct_name=extension.struct_name)

            method_info = MethodInfo(
                struct_name=extension.struct_name,
                method_name=method.name,
                param_types=param_types,
                return_type=return_type,
                param_names=param_names,
                self_mutable=self_mutable,
                is_init=method.is_init
            )

            struct_info.methods[method_key] = method_info

        # Process type assignments for interface conformances
        for iface_name in extension.conformances:
            if iface_name not in self.interfaces:
                continue  # Error will be reported below

            # Collect type assignments for this interface
            assignments: Dict[str, SawType] = {}
            for type_assign in extension.type_assignments:
                assignments[type_assign.name] = type_assign.assigned_type

            # Store the assignments
            self.type_assignments[(extension.struct_name, iface_name)] = assignments

        # Check interface conformances
        for iface_name in extension.conformances:
            if iface_name not in self.interfaces:
                self.reporter.error(
                    ErrorKind.UNDEFINED_VARIABLE,
                    f"unknown interface `{iface_name}`",
                    extension.line, extension.column
                )
                continue

            iface_info = self.interfaces[iface_name]
            self._check_interface_conformance(extension.struct_name, iface_info, struct_info, extension)

            # Track the conformance
            if extension.struct_name not in self.type_conformances:
                self.type_conformances[extension.struct_name] = []
            self.type_conformances[extension.struct_name].append(iface_name)

    def _check_interface_conformance(self, type_name: str, iface_info: InterfaceInfo,
                                      struct_info: StructInfo, extension: Extension):
        """Check that a type conforms to an interface by implementing all required methods."""
        for method_name, iface_method in iface_info.methods.items():
            if method_name not in struct_info.methods:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"type `{type_name}` does not implement required method `{method_name}` from interface `{iface_info.name}`",
                    extension.line, extension.column
                )
                continue

            impl_method = struct_info.methods[method_name]

            # Check self mutability matches
            if iface_method.self_mutable != impl_method.self_mutable:
                if iface_method.self_mutable:
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"method `{method_name}` should have `var self` to conform to interface `{iface_info.name}`",
                        extension.line, extension.column
                    )
                else:
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"method `{method_name}` should have immutable `self` to conform to interface `{iface_info.name}`",
                        extension.line, extension.column
                    )

            # Check return type matches (allow Self and associated types -> concrete types)
            if not self._types_compatible_for_interface(iface_method.return_type, impl_method.return_type,
                                                         type_name, iface_info.name):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"method `{method_name}` has return type `{impl_method.return_type}` but interface `{iface_info.name}` expects `{iface_method.return_type}`",
                    extension.line, extension.column
                )

            # Check parameter count (excluding self)
            iface_param_count = len(iface_method.param_types) - 1  # Exclude self placeholder
            impl_param_count = len(impl_method.param_types) - 1    # Exclude self
            if iface_param_count != impl_param_count:
                self.reporter.error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"method `{method_name}` takes {impl_param_count} parameter(s) but interface `{iface_info.name}` expects {iface_param_count}",
                    extension.line, extension.column
                )

        # Check that all required associated types are provided
        type_assigns = self.type_assignments.get((type_name, iface_info.name), {})
        for assoc_type_name in iface_info.associated_types:
            if assoc_type_name not in type_assigns:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"type `{type_name}` does not provide required associated type `{assoc_type_name}` from interface `{iface_info.name}`",
                    extension.line, extension.column,
                    hint=f"add `type {assoc_type_name} = SomeType` to the extension"
                )

    def _types_compatible_for_interface(self, iface_type: SawType, impl_type: SawType,
                                         self_type_name: str, iface_name: str = None) -> bool:
        """Check if implementation type matches interface type, with Self and associated type substitution."""
        # Resolve the interface type by substituting Self and associated types
        resolved_iface_type = self._resolve_interface_type(iface_type, self_type_name, iface_name)
        return self._types_compatible(resolved_iface_type, impl_type)

    def _resolve_interface_type(self, iface_type: SawType, self_type_name: str,
                                  iface_name: str = None) -> SawType:
        """Resolve Self and associated types in an interface type."""
        # Handle Self type (TypeKind.SELF)
        if iface_type.kind == TypeKind.SELF:
            return SawType(TypeKind.STRUCT, struct_name=self_type_name)
        if iface_type.kind == TypeKind.STRUCT and iface_type.struct_name:
            # Handle associated types
            if iface_name and (self_type_name, iface_name) in self.type_assignments:
                type_assigns = self.type_assignments[(self_type_name, iface_name)]
                if iface_type.struct_name in type_assigns:
                    return type_assigns[iface_type.struct_name]
            # Recursively resolve type args
            if iface_type.type_args:
                resolved_args = [self._resolve_interface_type(t, self_type_name, iface_name)
                                 for t in iface_type.type_args]
                return SawType(TypeKind.STRUCT, struct_name=iface_type.struct_name, type_args=resolved_args)
        elif iface_type.kind == TypeKind.OPTIONAL and iface_type.inner_type:
            resolved_inner = self._resolve_interface_type(iface_type.inner_type, self_type_name, iface_name)
            return SawType(TypeKind.OPTIONAL, inner_type=resolved_inner)
        elif iface_type.kind == TypeKind.TUPLE and iface_type.element_types:
            resolved_elems = [self._resolve_interface_type(t, self_type_name, iface_name)
                              for t in iface_type.element_types]
            return SawType(TypeKind.TUPLE, element_types=resolved_elems)
        elif iface_type.kind == TypeKind.ENUM and iface_type.type_args:
            resolved_args = [self._resolve_interface_type(t, self_type_name, iface_name)
                             for t in iface_type.type_args]
            return SawType(TypeKind.ENUM, enum_name=iface_type.enum_name, type_args=resolved_args)
        return iface_type

    def _check_extension(self, extension: Extension):
        """Type check all methods in an extension."""
        for method in extension.methods:
            self._check_method(extension.struct_name, method)

    def _check_method(self, struct_name: str, method: Method):
        """Type check a method body."""
        self.current_method = method
        self.found_return_with_value = False

        # Create new scope for method
        self.current_scope = Scope()

        # Add parameters to scope
        for param in method.parameters:
            info = VariableInfo(param.type, mutable=False, line=method.line, column=method.column)
            self.current_scope.define(param.name, info)

        # Check body
        body_type = self._check_block(method.body)

        # For init methods, check return type
        expected_return = method.return_type
        if method.is_init:
            expected_return = SawType(TypeKind.STRUCT, struct_name=struct_name)

        if expected_return.kind != TypeKind.VOID:
            if body_type is None and not self.found_return_with_value:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"method `{method.name}` should return `{expected_return}` but body has no value",
                    method.line, method.column
                )
            elif body_type is not None and not self._types_compatible(body_type, expected_return):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"method `{method.name}` should return `{expected_return}` but returns `{body_type}`",
                    method.line, method.column
                )

        self.current_method = None

    def _check_function(self, func: Function):
        """Type check a function body."""
        # Skip type checking generic function bodies - they'll be checked at instantiation
        if func.type_params:
            return

        self.current_function = func
        self.found_return_with_value = False  # Reset for each function

        # Create new scope for function
        self.current_scope = Scope()

        # Add parameters to scope (resolve types first)
        for param in func.parameters:
            resolved_type = self._resolve_type(param.type)
            info = VariableInfo(resolved_type, mutable=False, line=func.line, column=func.column)
            self.current_scope.define(param.name, info)

        # Check body
        body_type = self._check_block(func.body)

        # Resolve return type
        resolved_return_type = self._resolve_type(func.return_type)

        # Check return type matches
        if resolved_return_type.kind != TypeKind.VOID:
            # Function can return a value via either:
            # 1. An explicit return statement (found_return_with_value)
            # 2. A final expression in the body (body_type)
            if body_type is None and not self.found_return_with_value:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"function `{func.name}` should return `{resolved_return_type}` but body has no value",
                    func.line, func.column
                )
            elif body_type is not None and not self._types_compatible(body_type, resolved_return_type):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"function `{func.name}` should return `{resolved_return_type}` but returns `{body_type}`",
                    func.line, func.column
                )

        self.current_function = None

    def _check_block(self, block: Block) -> Optional[SawType]:
        """Check a block and return its type (from final expression)."""
        # Create new scope for block
        old_scope = self.current_scope
        self.current_scope = Scope(parent=old_scope)

        for stmt in block.statements:
            self._check_statement(stmt)

        result_type = None
        if block.final_expr is not None:
            result_type = self._check_expression(block.final_expr)

        # Restore scope
        self.current_scope = old_scope

        return result_type

    def _check_statement(self, stmt: Statement):
        """Check a statement."""
        # Handle dual-purpose nodes (Expressions used as Statements)
        if isinstance(stmt, WhileExpr):
            self._check_while_expr(stmt)
            return
        if isinstance(stmt, ForLoop):
            self._check_for_loop(stmt)
            return

        # Visitor dispatch for all other statements
        method_name = f'visit_{stmt.__class__.__name__}'
        visitor = getattr(self, method_name, None)
        if visitor:
            visitor(stmt)

    # ===== Statement Visitor Methods =====

    def visit_LetStatement(self, stmt: LetStatement):
        self._check_let_statement(stmt)

    def visit_AssignStatement(self, stmt: AssignStatement):
        self._check_assign_statement(stmt)

    def visit_ReturnStatement(self, stmt: ReturnStatement):
        self._check_return_statement(stmt)

    def visit_GuardLetStatement(self, stmt: GuardLetStatement):
        self._check_guard_let_statement(stmt)

    def visit_BreakStatement(self, stmt: BreakStatement):
        self._check_break_statement(stmt)

    def visit_ContinueStatement(self, stmt: ContinueStatement):
        self._check_continue_statement(stmt)

    def visit_ExpressionStatement(self, stmt: ExpressionStatement):
        self._check_expression(stmt.expression)

    def _check_let_statement(self, stmt: LetStatement):
        """Check a let/var statement."""
        # Check for duplicate in current scope
        existing = self.current_scope.lookup_local(stmt.name)
        if existing:
            self.reporter.error(
                ErrorKind.DUPLICATE_VARIABLE,
                f"variable `{stmt.name}` is already defined in this scope",
                stmt.line, stmt.column,
                hint=f"previous definition was at line {existing.line}"
            )
            return

        # Infer or check type
        value_type = self._check_expression(stmt.value)

        if stmt.type_annotation:
            # Resolve type aliases in the annotation
            resolved_type = self._resolve_type(stmt.type_annotation)
            # allow_literal_to_distinct=True because let/var initialization allows primitives to
            # initialize distinct types (e.g., `let x: MyInt = 21`)
            if not self._types_compatible(value_type, resolved_type, allow_literal_to_distinct=True):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot assign `{value_type}` to variable of type `{stmt.type_annotation}`",
                    stmt.line, stmt.column
                )
            # Check integer literal range for fixed-width types
            if isinstance(stmt.value, IntLiteral):
                self._check_integer_literal_range(stmt.value, resolved_type)
            var_type = resolved_type
        else:
            var_type = value_type

        # Check for NoCopy types - cannot copy from another variable (but move is OK)
        if isinstance(stmt.value, Identifier) and self._is_no_copy_type(value_type):
            self.reporter.error(
                ErrorKind.CANNOT_COPY,
                f"cannot copy value of type `{value_type}` which implements NoCopy",
                stmt.line, stmt.column,
                hint="use `move` to transfer ownership instead"
            )
        # MoveExpr is allowed - mark the source variable as moved
        elif isinstance(stmt.value, MoveExpr):
            self.moved_variables.add(stmt.value.variable)

        # Add to scope
        if var_type:
            info = VariableInfo(var_type, stmt.mutable, stmt.line, stmt.column)
            self.current_scope.define(stmt.name, info)

    def _check_guard_let_statement(self, stmt: GuardLetStatement):
        """Check a guard let/var statement for optional binding."""
        # Check for duplicate in current scope
        existing = self.current_scope.lookup_local(stmt.name)
        if existing:
            self.reporter.error(
                ErrorKind.DUPLICATE_VARIABLE,
                f"variable `{stmt.name}` is already defined in this scope",
                stmt.line, stmt.column,
                hint=f"previous definition was at line {existing.line}"
            )
            return

        # Check the optional expression
        optional_type = self._check_expression(stmt.optional_expr)

        if optional_type is None:
            return

        # Must be an optional type
        if optional_type.kind != TypeKind.OPTIONAL:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"'guard let' requires an optional type, got `{optional_type}`",
                stmt.line, stmt.column
            )
            return

        # Get the unwrapped type
        inner_type = optional_type.inner_type
        if inner_type is None:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot determine type of bound variable from None literal",
                stmt.line, stmt.column
            )
            return

        # Check the else branch (should contain early exit)
        # Create a temporary scope for the else branch
        old_scope = self.current_scope
        self.current_scope = Scope(parent=old_scope)
        self._check_block(stmt.else_branch)
        self.current_scope = old_scope

        # Verify else branch has early exit (return, break, continue)
        if not self._block_has_early_exit(stmt.else_branch):
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                "'guard' else block must exit the scope (return, break, or continue)",
                stmt.line, stmt.column,
                hint="add 'return', 'break', or 'continue' to the else block"
            )

        # Add the bound variable to the current (outer) scope
        # This is the key difference from if-let: the variable is available after the guard
        info = VariableInfo(inner_type, stmt.mutable, stmt.line, stmt.column)
        self.current_scope.define(stmt.name, info)

    def _check_assign_statement(self, stmt: AssignStatement):
        """Check an assignment statement."""
        # Handle both simple variable assignment and field assignment
        if isinstance(stmt.target, Identifier):
            # Simple variable assignment: x = value
            var_info = self.current_scope.lookup(stmt.target.name)
            if not var_info:
                self.reporter.error(
                    ErrorKind.UNDEFINED_VARIABLE,
                    f"undefined variable `{stmt.target.name}`",
                    stmt.line, stmt.column
                )
                return

            # Check mutability
            if not var_info.mutable:
                self.reporter.error(
                    ErrorKind.IMMUTABLE_ASSIGNMENT,
                    f"cannot assign to immutable variable `{stmt.target.name}`",
                    stmt.line, stmt.column,
                    hint="consider using `var` instead of `let` to make it mutable"
                )

            # Check type
            value_type = self._check_expression(stmt.value)
            if value_type and not self._types_compatible(value_type, var_info.type):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot assign `{value_type}` to variable of type `{var_info.type}`",
                    stmt.line, stmt.column
                )

            # Check for NoCopy types - cannot copy from another variable (but move is OK)
            if isinstance(stmt.value, Identifier) and self._is_no_copy_type(value_type):
                self.reporter.error(
                    ErrorKind.CANNOT_COPY,
                    f"cannot copy value of type `{value_type}` which implements NoCopy",
                    stmt.line, stmt.column,
                    hint="use `move` to transfer ownership instead"
                )
            # MoveExpr is allowed - mark the source variable as moved
            elif isinstance(stmt.value, MoveExpr):
                self.moved_variables.add(stmt.value.variable)

        elif isinstance(stmt.target, MemberAccess):
            # Field assignment: obj.field = value
            obj_type = self._check_expression(stmt.target.object)
            if not obj_type:
                return

            # Must be a struct type
            if obj_type.kind != TypeKind.STRUCT:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot access field on non-struct type `{obj_type}`",
                    stmt.target.line, stmt.target.column
                )
                return

            # Check if field exists
            struct_info = self.structs.get(obj_type.struct_name)
            if not struct_info:
                return

            if stmt.target.member not in struct_info.fields:
                self.reporter.error(
                    ErrorKind.UNDEFINED_VARIABLE,
                    f"struct `{obj_type.struct_name}` has no field `{stmt.target.member}`",
                    stmt.target.line, stmt.target.column
                )
                return

            field_type = struct_info.fields[stmt.target.member]

            # Check value type
            value_type = self._check_expression(stmt.value)
            if value_type and not self._types_compatible(value_type, field_type):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot assign `{value_type}` to field of type `{field_type}`",
                    stmt.line, stmt.column
                )

        elif isinstance(stmt.target, ArrayIndex):
            # Array or pointer element assignment: arr[i] = value or ptr[i] = value
            container_type = self._check_expression(stmt.target.array_expr)
            if not container_type:
                return

            # Must be an array or pointer type
            if container_type.kind == TypeKind.ARRAY:
                element_type = container_type.array_element_type
                # For arrays, check binding mutability
                if isinstance(stmt.target.array_expr, Identifier):
                    var_info = self.current_scope.lookup(stmt.target.array_expr.name)
                    if var_info and not var_info.mutable:
                        self.reporter.error(
                            ErrorKind.IMMUTABLE_ASSIGNMENT,
                            f"cannot assign to element of immutable array `{stmt.target.array_expr.name}`",
                            stmt.line, stmt.column,
                            hint="consider using `var` instead of `let` to make it mutable"
                        )
            elif container_type.kind == TypeKind.POINTER:
                # For pointers, check pointer mutability (UnsafePointer vs UnsafeConstPointer)
                if not container_type.pointer_mutable:
                    self.reporter.error(
                        ErrorKind.IMMUTABLE_ASSIGNMENT,
                        f"cannot write through UnsafeConstPointer (use UnsafePointer for mutable access)",
                        stmt.line, stmt.column
                    )
                    return
                element_type = container_type.inner_type
            else:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot index into type `{container_type}`",
                    stmt.target.line, stmt.target.column
                )
                return

            # Check index type
            index_type = self._check_expression(stmt.target.index)
            if index_type:
                index_underlying = self._get_underlying_type(index_type)
                if index_underlying.kind != TypeKind.INT:
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"index must be Int, got `{index_type}`",
                        stmt.target.index.line, stmt.target.index.column
                    )

            # Check value type matches element type
            value_type = self._check_expression(stmt.value)
            if value_type and element_type:
                if not self._types_compatible(value_type, element_type):
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"cannot assign `{value_type}` to element of type `{element_type}`",
                        stmt.line, stmt.column
                    )

        else:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                "invalid assignment target",
                stmt.line, stmt.column
            )

    def _check_return_statement(self, stmt: ReturnStatement):
        """Check a return statement."""
        if self.current_function is None:
            return

        expected = self.current_function.return_type

        if stmt.value is None:
            if expected.kind != TypeKind.VOID:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"function should return `{expected}` but return has no value",
                    stmt.line, stmt.column
                )
        else:
            value_type = self._check_expression(stmt.value)
            if value_type and expected.kind == TypeKind.VOID:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"function returns void but return has a value of type `{value_type}`",
                    stmt.line, stmt.column
                )
            elif value_type and not self._types_compatible(value_type, expected):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"expected return type `{expected}` but got `{value_type}`",
                    stmt.line, stmt.column
                )
            else:
                # Mark that we found a valid return statement with a value
                self.found_return_with_value = True

    def _check_while_expr(self, stmt: WhileExpr):
        """Check a while loop used as a statement (no return value expected)."""
        # If condition is present, it must be a Bool
        if stmt.condition:
            cond_type = self._check_expression(stmt.condition)
            if cond_type and cond_type.kind != TypeKind.BOOL:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"while condition must be Bool, got `{cond_type}`",
                    stmt.line, stmt.column
                )

        # Check body with increased loop depth but NO break type tracking
        # (statements don't need to return values)
        self.loop_depth += 1
        self._check_block(stmt.body)
        self.loop_depth -= 1

    def _check_while_expr_as_expression(self, expr: WhileExpr) -> Optional[SawType]:
        """Check a while loop expression and return its type."""
        # If condition is present, it must be a Bool
        if expr.condition:
            cond_type = self._check_expression(expr.condition)
            if cond_type and cond_type.kind != TypeKind.BOOL:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"while condition must be Bool, got `{cond_type}`",
                    expr.line, expr.column
                )

        is_infinite = expr.condition is None

        # Push loop info onto stack: (break_type, is_infinite, has_break)
        # break_type will be determined by the first break statement
        self.loop_break_info.append((None, is_infinite, False))

        # Check body with increased loop depth
        self.loop_depth += 1
        self._check_block(expr.body)
        self.loop_depth -= 1

        # Pop loop info and determine return type
        break_type, _, has_break = self.loop_break_info.pop()

        if is_infinite:
            # Infinite loop: must have at least one break with value
            if not has_break:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    "infinite while loop used as expression must have at least one `break` statement",
                    expr.line, expr.column
                )
                return None
            if break_type is None:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    "infinite while loop used as expression must `break` with a value",
                    expr.line, expr.column
                )
                return None
            # Return the break type directly (non-optional)
            expr.result_type = break_type
            return break_type
        else:
            # Conditional loop: returns Optional<break_type>
            if break_type is None:
                # No breaks with values, returns Void
                expr.result_type = SawType(TypeKind.VOID)
                return SawType(TypeKind.VOID)
            # Wrap break type in Optional
            result = SawType(TypeKind.OPTIONAL, inner_type=break_type)
            expr.result_type = result
            return result

    def _check_for_loop(self, stmt: ForLoop):
        """Check a for loop statement."""
        # Check the iterable expression
        iterable_type = self._check_expression(stmt.iterable)

        # Determine the loop variable type based on the iterable
        loop_var_type: Optional[SawType] = None

        if isinstance(stmt.iterable, RangeExpr):
            # Range expression - loop variable is Int
            loop_var_type = SawType(TypeKind.INT)
        else:
            # Check if the type implements Iterator interface
            loop_var_type = self._get_iterator_item_type(iterable_type, stmt.line, stmt.column)
            if loop_var_type is None:
                loop_var_type = SawType(TypeKind.INT)  # Default to Int on error

        # Create new scope for loop body with loop variable
        old_scope = self.current_scope
        self.current_scope = Scope(parent=old_scope)

        # Add loop variable to scope (immutable by default)
        self.current_scope.define(
            stmt.variable,
            VariableInfo(loop_var_type, mutable=False, line=stmt.line, column=stmt.column)
        )

        # Check body with increased loop depth
        self.loop_depth += 1
        self._check_block(stmt.body)
        self.loop_depth -= 1

        # Restore scope
        self.current_scope = old_scope

    def _check_for_loop_as_expression(self, expr: ForLoop) -> Optional[SawType]:
        """Check a for loop expression and return its type (Optional<T> from break values)."""
        # Check the iterable expression
        iterable_type = self._check_expression(expr.iterable)

        # Determine the loop variable type based on the iterable
        loop_var_type: Optional[SawType] = None

        if isinstance(expr.iterable, RangeExpr):
            # Range expression - loop variable is Int
            loop_var_type = SawType(TypeKind.INT)
        else:
            # Check if the type implements Iterator interface
            loop_var_type = self._get_iterator_item_type(iterable_type, expr.line, expr.column)
            if loop_var_type is None:
                loop_var_type = SawType(TypeKind.INT)  # Default to Int on error

        # For loops are always conditional (have a finite range), so return Optional<T>
        # Push loop info onto stack: (break_type, is_infinite=False, has_break)
        self.loop_break_info.append((None, False, False))

        # Create new scope for loop body with loop variable
        old_scope = self.current_scope
        self.current_scope = Scope(parent=old_scope)

        # Add loop variable to scope (immutable by default)
        self.current_scope.define(
            expr.variable,
            VariableInfo(loop_var_type, mutable=False, line=expr.line, column=expr.column)
        )

        # Check body with increased loop depth
        self.loop_depth += 1
        self._check_block(expr.body)
        self.loop_depth -= 1

        # Restore scope
        self.current_scope = old_scope

        # Pop loop info and determine return type
        break_type, _, has_break = self.loop_break_info.pop()

        # For loops are conditional, so return Optional<break_type>
        if break_type is None:
            # No breaks with values, returns Void
            expr.result_type = SawType(TypeKind.VOID)
            return SawType(TypeKind.VOID)
        # Wrap break type in Optional
        result = SawType(TypeKind.OPTIONAL, inner_type=break_type)
        expr.result_type = result
        return result

    def _get_iterator_item_type(self, iterable_type: Optional[SawType], line: int, column: int) -> Optional[SawType]:
        """Get the Item type for a type that implements Iterator interface.

        Returns None if the type doesn't implement Iterator, and reports an error.
        """
        if iterable_type is None:
            return None

        # The type must be a struct
        if iterable_type.kind != TypeKind.STRUCT:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"for loop requires an Iterator, got `{iterable_type}`",
                line, column,
                hint="use `for i in start..end {{ ... }}` for range iteration"
            )
            return None

        type_name = iterable_type.struct_name

        # Check if the type conforms to Iterator
        conformances = self.type_conformances.get(type_name, [])
        if "Iterator" not in conformances:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"type `{type_name}` does not implement Iterator",
                line, column,
                hint="add `extension {}: Iterator {{ type Item = ...; func next(var self) -> Item? {{ ... }} }}`".format(type_name)
            )
            return None

        # Get the Item associated type
        type_assigns = self.type_assignments.get((type_name, "Iterator"), {})
        if "Item" not in type_assigns:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"Iterator implementation for `{type_name}` is missing associated type `Item`",
                line, column
            )
            return None

        return type_assigns["Item"]

    def _check_range_expr(self, expr: RangeExpr) -> Optional[SawType]:
        """Check a range expression: start..end"""
        start_type = self._check_expression(expr.start)
        end_type = self._check_expression(expr.end)

        if start_type is None or end_type is None:
            return None

        # Both start and end must be Int
        if start_type.kind != TypeKind.INT:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"range start must be Int, got `{start_type}`",
                expr.line, expr.column
            )

        if end_type.kind != TypeKind.INT:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"range end must be Int, got `{end_type}`",
                expr.line, expr.column
            )

        # Return a special "Range" type - for now just use VOID as placeholder
        # The for loop handles ranges specially
        return SawType(TypeKind.VOID)

    def _check_break_statement(self, stmt: BreakStatement):
        """Check a break statement."""
        if self.loop_depth == 0:
            self.reporter.error(
                ErrorKind.INVALID_BREAK_CONTINUE,
                "`break` can only be used inside a loop",
                stmt.line, stmt.column
            )
            return

        # Type check the break value if present
        value_type = None
        if stmt.value:
            value_type = self._check_expression(stmt.value)

        # Update loop break info if we're tracking it
        if self.loop_break_info:
            existing_type, is_infinite, _ = self.loop_break_info[-1]

            # Mark that we found a break
            self.loop_break_info[-1] = (existing_type or value_type, is_infinite, True)

            # If there's an existing break type, validate compatibility
            if existing_type and value_type:
                if not self._types_compatible(value_type, existing_type):
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"break value type `{value_type}` incompatible with expected type `{existing_type}`",
                        stmt.line, stmt.column
                    )
            elif not existing_type and value_type:
                # First break with a value sets the type
                self.loop_break_info[-1] = (value_type, is_infinite, True)

    def _check_continue_statement(self, stmt: ContinueStatement):
        """Check a continue statement."""
        if self.loop_depth == 0:
            self.reporter.error(
                ErrorKind.INVALID_BREAK_CONTINUE,
                "`continue` can only be used inside a loop",
                stmt.line, stmt.column
            )

    def _check_expression(self, expr: Expression) -> Optional[SawType]:
        """Check an expression and return its type."""
        method_name = f'visit_{expr.__class__.__name__}'
        visitor = getattr(self, method_name, None)
        if visitor is None:
            return None
        return visitor(expr)

    # ===== Expression Visitor Methods =====

    def visit_IntLiteral(self, expr: IntLiteral) -> Optional[SawType]:
        return SawType(TypeKind.INT)

    def visit_FloatLiteral(self, expr: FloatLiteral) -> Optional[SawType]:
        return SawType(TypeKind.FLOAT)

    def visit_BoolLiteral(self, expr: BoolLiteral) -> Optional[SawType]:
        return SawType(TypeKind.BOOL)

    def visit_StringLiteral(self, expr: StringLiteral) -> Optional[SawType]:
        return SawType(TypeKind.STRING)

    def visit_Identifier(self, expr: Identifier) -> Optional[SawType]:
        return self._check_identifier(expr)

    def visit_BinaryOp(self, expr: BinaryOp) -> Optional[SawType]:
        return self._check_binary_op(expr)

    def visit_UnaryOp(self, expr: UnaryOp) -> Optional[SawType]:
        return self._check_unary_op(expr)

    def visit_MoveExpr(self, expr: MoveExpr) -> Optional[SawType]:
        return self._check_move_expr(expr)

    def visit_CastExpr(self, expr: CastExpr) -> Optional[SawType]:
        return self._check_cast_expr(expr)

    def visit_FunctionCall(self, expr: FunctionCall) -> Optional[SawType]:
        return self._check_function_call(expr)

    def visit_IfExpr(self, expr: IfExpr) -> Optional[SawType]:
        return self._check_if_expr(expr)

    def visit_IfLetExpr(self, expr: IfLetExpr) -> Optional[SawType]:
        return self._check_if_let_expr(expr)

    def visit_TupleLiteral(self, expr: TupleLiteral) -> Optional[SawType]:
        return self._check_tuple_literal(expr)

    def visit_TupleIndex(self, expr: TupleIndex) -> Optional[SawType]:
        return self._check_tuple_index(expr)

    def visit_ArrayLiteral(self, expr: ArrayLiteral) -> Optional[SawType]:
        return self._check_array_literal(expr)

    def visit_ArrayIndex(self, expr: ArrayIndex) -> Optional[SawType]:
        return self._check_array_index(expr)

    def visit_MemberAccess(self, expr: MemberAccess) -> Optional[SawType]:
        return self._check_member_access(expr)

    def visit_StructInit(self, expr: StructInit) -> Optional[SawType]:
        return self._check_struct_init(expr)

    def visit_NoneLiteral(self, expr: NoneLiteral) -> Optional[SawType]:
        return self._check_none_literal(expr)

    def visit_ForceUnwrap(self, expr: ForceUnwrap) -> Optional[SawType]:
        return self._check_force_unwrap(expr)

    def visit_NilCoalesce(self, expr: NilCoalesce) -> Optional[SawType]:
        return self._check_nil_coalesce(expr)

    def visit_OptionalChain(self, expr: OptionalChain) -> Optional[SawType]:
        return self._check_optional_chain(expr)

    def visit_MethodCall(self, expr: MethodCall) -> Optional[SawType]:
        return self._check_method_call(expr)

    def visit_SelfExpr(self, expr: SelfExpr) -> Optional[SawType]:
        return self._check_self_expr(expr)

    def visit_EnumInit(self, expr: EnumInit) -> Optional[SawType]:
        return self._check_enum_init(expr)

    def visit_MatchExpr(self, expr: MatchExpr) -> Optional[SawType]:
        return self._check_match_expr(expr)

    def visit_WhileExpr(self, expr: WhileExpr) -> Optional[SawType]:
        return self._check_while_expr_as_expression(expr)

    def visit_RangeExpr(self, expr: RangeExpr) -> Optional[SawType]:
        return self._check_range_expr(expr)

    def visit_ForLoop(self, expr: ForLoop) -> Optional[SawType]:
        return self._check_for_loop_as_expression(expr)

    def visit_ClosureExpr(self, expr: ClosureExpr) -> Optional[SawType]:
        return self._check_closure(expr)

    def _check_identifier(self, expr: Identifier) -> Optional[SawType]:
        """Check an identifier reference."""
        # Check for use-after-move
        if expr.name in self.moved_variables:
            self.reporter.error(
                ErrorKind.USE_AFTER_MOVE,
                f"use of moved variable `{expr.name}`",
                expr.line, expr.column,
                hint="value was moved and can no longer be used"
            )
            return None

        var_info = self.current_scope.lookup(expr.name)
        if not var_info:
            self.reporter.error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"undefined variable `{expr.name}`",
                expr.line, expr.column
            )
            return None
        return var_info.type

    def _check_move_expr(self, expr: MoveExpr) -> Optional[SawType]:
        """Check a move expression."""
        # Check for use-after-move (can't move already-moved variable)
        if expr.variable in self.moved_variables:
            self.reporter.error(
                ErrorKind.USE_AFTER_MOVE,
                f"use of moved variable `{expr.variable}`",
                expr.line, expr.column,
                hint="value was already moved and can no longer be used"
            )
            return None

        var_info = self.current_scope.lookup(expr.variable)
        if not var_info:
            self.reporter.error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"undefined variable `{expr.variable}`",
                expr.line, expr.column
            )
            return None

        # Note: We don't mark as moved here - that's done in _check_let/assign_statement
        # This allows us to properly type-check the expression first
        return var_info.type

    def _check_cast_expr(self, expr: CastExpr) -> Optional[SawType]:
        """Check a type cast expression: expr as Type"""
        from_type = self._check_expression(expr.expr)
        if from_type is None:
            return None

        to_type = self._resolve_type(expr.target_type)

        # Define valid integer kinds
        int_kinds = {
            TypeKind.INT, TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
            TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64
        }

        # Integer to integer cast
        if from_type.kind in int_kinds and to_type.kind in int_kinds:
            return to_type

        # Pointer to pointer cast
        if from_type.kind == TypeKind.POINTER and to_type.kind == TypeKind.POINTER:
            return to_type

        # String to/from UnsafePointer<Int8> cast
        # String is represented as i8* at runtime, so this is safe
        if from_type.kind == TypeKind.STRING and to_type.kind == TypeKind.POINTER:
            if to_type.inner_type and to_type.inner_type.kind == TypeKind.INT8:
                return to_type
        if from_type.kind == TypeKind.POINTER and to_type.kind == TypeKind.STRING:
            if from_type.inner_type and from_type.inner_type.kind == TypeKind.INT8:
                return to_type

        self.reporter.error(
            ErrorKind.TYPE_MISMATCH,
            f"cannot cast `{from_type}` to `{to_type}`",
            expr.line, expr.column
        )
        return None

    def _check_binary_op(self, expr: BinaryOp) -> Optional[SawType]:
        """Check a binary operation."""
        left_type = self._check_expression(expr.left)
        right_type = self._check_expression(expr.right)

        if left_type is None or right_type is None:
            return None

        # Get underlying types for operation checking (for distinct types like `type MyInt = Int`)
        left_underlying = self._get_underlying_type(left_type)
        right_underlying = self._get_underlying_type(right_type)

        # Arithmetic operators
        if expr.op in ['+', '-', '*', '/']:
            # Pointer arithmetic: ptr + int or ptr - int
            if expr.op in ['+', '-'] and left_underlying.kind == TypeKind.POINTER:
                if right_underlying.kind == TypeKind.INT:
                    return left_type  # Returns same pointer type
                else:
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"pointer arithmetic requires Int offset, got `{right_type}`",
                        expr.line, expr.column
                    )
                    return None
            elif left_underlying.kind == TypeKind.INT and right_underlying.kind == TypeKind.INT:
                # Return the original left type (preserves distinct types)
                return left_type
            elif left_underlying.kind in [TypeKind.INT, TypeKind.FLOAT] and \
                 right_underlying.kind in [TypeKind.INT, TypeKind.FLOAT]:
                return SawType(TypeKind.FLOAT)
            else:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `{expr.op}` cannot be applied to `{left_type}` and `{right_type}`",
                    expr.line, expr.column
                )
                return None

        # Modulo operator (integers only)
        elif expr.op == '%':
            if left_underlying.kind == TypeKind.INT and right_underlying.kind == TypeKind.INT:
                return left_type  # Preserve distinct type
            else:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `%` requires integer operands, got `{left_type}` and `{right_type}`",
                    expr.line, expr.column
                )
                return None

        # Logical operators
        elif expr.op in ['&&', '||']:
            if left_underlying.kind == TypeKind.BOOL and right_underlying.kind == TypeKind.BOOL:
                return SawType(TypeKind.BOOL)
            else:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `{expr.op}` requires Bool operands, got `{left_type}` and `{right_type}`",
                    expr.line, expr.column
                )
                return None

        # Comparison operators
        elif expr.op in ['==', '!=', '<', '>', '<=', '>=']:
            # Enums only support == and !=, not ordering operators
            if left_type.kind == TypeKind.ENUM or right_type.kind == TypeKind.ENUM:
                if expr.op in ['<', '>', '<=', '>=']:
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"enum types do not support ordering operators (`{expr.op}`), only `==` and `!=`",
                        expr.line, expr.column
                    )
                    return None

            if not self._types_compatible(left_type, right_type):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot compare `{left_type}` with `{right_type}`",
                    expr.line, expr.column
                )
            return SawType(TypeKind.BOOL)

        return None

    def _check_unary_op(self, expr: UnaryOp) -> Optional[SawType]:
        """Check a unary operation."""
        operand_type = self._check_expression(expr.operand)
        if operand_type is None:
            return None

        # Get underlying type for operation checking
        underlying = self._get_underlying_type(operand_type)

        if expr.op == '-':
            if underlying.kind in [TypeKind.INT, TypeKind.FLOAT]:
                return operand_type  # Preserve distinct type
            else:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `-` cannot be applied to `{operand_type}`",
                    expr.line, expr.column
                )
                return None

        elif expr.op == 'not':
            if underlying.kind == TypeKind.BOOL:
                return SawType(TypeKind.BOOL)
            else:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `not` requires Bool operand, got `{operand_type}`",
                    expr.line, expr.column
                )
                return None

        return None

    def _check_function_call(self, expr: FunctionCall) -> Optional[SawType]:
        """Check a function call.

        Arguments are Argument objects with .value and optional .name.
        """
        # Handle built-in print specially
        if expr.name == "print":
            if len(expr.arguments) > 1:
                self.reporter.error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`print` takes 0 or 1 arguments, but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
            # Check argument type (print accepts any type)
            for arg in expr.arguments:
                self._check_expression(arg.value)
            return SawType(TypeKind.VOID)

        # Handle built-in sizeof<T>() function
        if expr.name == "sizeof":
            if len(expr.arguments) != 0:
                self.reporter.error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`sizeof` takes no arguments, but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
            if not expr.type_args or len(expr.type_args) != 1:
                self.reporter.error(
                    ErrorKind.TYPE_ERROR,
                    "`sizeof` requires exactly one type argument: sizeof<T>()",
                    expr.line, expr.column
                )
                return None
            # Resolve the type argument to validate it exists
            resolved_type = self._resolve_type(expr.type_args[0])
            if resolved_type is None:
                return None
            return SawType(TypeKind.INT)

        # Check if this is a call to a function-typed variable (closure)
        var_info = self.current_scope.lookup(expr.name)
        if var_info and var_info.type.kind == TypeKind.FUNCTION:
            # Calling a closure variable
            func_type = var_info.type
            param_types = func_type.param_types or []
            return_type = func_type.func_return_type or SawType(TypeKind.VOID)

            # Check argument count
            if len(expr.arguments) != len(param_types):
                self.reporter.error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"closure takes {len(param_types)} argument(s), "
                    f"but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
                return return_type

            # Check argument types
            for i, (arg, expected_type) in enumerate(zip(expr.arguments, param_types)):
                if isinstance(arg.value, ClosureExpr):
                    arg_type = self._check_closure(arg.value, expected_type)
                else:
                    arg_type = self._check_expression(arg.value)
                if arg_type and not self._types_compatible(arg_type, expected_type):
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"argument {i + 1} expects `{expected_type}` but got `{arg_type}`",
                        arg.value.line, arg.value.column
                    )

            return return_type

        # Look up function
        func_info = self.functions.get(expr.name)
        if not func_info:
            # Check if this is actually a struct init call (e.g., Vector<Int>())
            # This happens when parser sees empty parens and treats it as function call
            if expr.name in self.structs:
                # Convert FunctionCall to StructInit and check that instead
                from ast_nodes import StructInit, Argument
                # Convert arguments to field inits (name: value pairs)
                field_inits = []
                for arg in expr.arguments:
                    if arg.name:
                        field_inits.append((arg.name, arg.value))
                    else:
                        # Positional argument - not supported for struct init
                        self.reporter.error(
                            ErrorKind.TYPE_MISMATCH,
                            f"struct initialization requires named arguments",
                            arg.value.line, arg.value.column
                        )
                        return None
                struct_init = StructInit(
                    struct_name=expr.name,
                    field_inits=field_inits,
                    type_args=expr.type_args,
                    line=expr.line,
                    column=expr.column
                )
                result = self._check_struct_init(struct_init)
                # Copy resolved_init_params back to the FunctionCall for codegen
                if hasattr(struct_init, 'resolved_init_params'):
                    expr.resolved_init_params = struct_init.resolved_init_params
                return result

            self.reporter.error(
                ErrorKind.UNDEFINED_FUNCTION,
                f"undefined function `{expr.name}`",
                expr.line, expr.column
            )
            return None

        # Handle generic functions
        if func_info.type_params:
            # Generic function - require type arguments
            if not expr.type_args:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"generic function `{expr.name}` requires type arguments",
                    expr.line, expr.column,
                    hint=f"use `{expr.name}<Type>(...)`"
                )
                return None

            # Check type argument count
            if len(expr.type_args) != len(func_info.type_params):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"function `{expr.name}` expects {len(func_info.type_params)} type argument(s), "
                    f"but {len(expr.type_args)} were given",
                    expr.line, expr.column
                )
                return None

            # Build type substitution map and check bounds
            type_map: Dict[str, SawType] = {}
            for type_param, type_arg in zip(func_info.type_params, expr.type_args):
                # Resolve the type argument
                resolved_arg = self._resolve_type(type_arg)
                type_map[type_param.name] = resolved_arg

                # Check interface bounds
                for bound in type_param.bounds:
                    if bound not in self.interfaces:
                        self.reporter.error(
                            ErrorKind.UNDEFINED_VARIABLE,
                            f"unknown interface `{bound}` in type parameter bound",
                            expr.line, expr.column
                        )
                        continue

                    # Check if the concrete type satisfies the bound
                    concrete_type_name = None
                    if resolved_arg.kind == TypeKind.STRUCT:
                        concrete_type_name = resolved_arg.struct_name
                    elif resolved_arg.kind == TypeKind.ENUM:
                        concrete_type_name = resolved_arg.enum_name

                    if concrete_type_name:
                        conformances = self.type_conformances.get(concrete_type_name, [])
                        if bound not in conformances:
                            self.reporter.error(
                                ErrorKind.TYPE_MISMATCH,
                                f"type `{resolved_arg}` does not implement interface `{bound}`",
                                expr.line, expr.column,
                                hint=f"add `extension {concrete_type_name}: {bound} {{ ... }}`"
                            )
                        else:
                            # Add associated type mappings to type_map
                            # For `T: Container` where T=IntBox, add `Item -> Int`
                            type_assigns = self.type_assignments.get((concrete_type_name, bound), {})
                            for assoc_name, assoc_type in type_assigns.items():
                                type_map[assoc_name] = assoc_type

            # Substitute type parameters in param types and return type
            param_types = [t.substitute(type_map) for t in func_info.param_types]
            return_type = func_info.return_type.substitute(type_map)
        else:
            # Non-generic function
            if expr.type_args:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"function `{expr.name}` is not generic but was called with type arguments",
                    expr.line, expr.column
                )
            param_types = func_info.param_types
            return_type = func_info.return_type

        # Check argument count
        if len(expr.arguments) != len(param_types):
            self.reporter.error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"function `{expr.name}` takes {len(param_types)} argument(s), "
                f"but {len(expr.arguments)} were given",
                expr.line, expr.column
            )
            return return_type

        # Check argument types
        for i, (arg, expected_type) in enumerate(zip(expr.arguments, param_types)):
            # Special handling for closures - pass expected type for inference
            if isinstance(arg.value, ClosureExpr):
                arg_type = self._check_closure(arg.value, expected_type)
            else:
                arg_type = self._check_expression(arg.value)

            if arg_type and not self._types_compatible(arg_type, expected_type):
                param_name = func_info.param_names[i]
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument `{param_name}` expects `{expected_type}` but got `{arg_type}`",
                    arg.value.line, arg.value.column
                )

        return return_type

    def _check_if_expr(self, expr: IfExpr) -> Optional[SawType]:
        """Check an if expression."""
        cond_type = self._check_expression(expr.condition)

        if cond_type and cond_type.kind != TypeKind.BOOL:
            # Allow int as condition (truthy/falsy)
            if cond_type.kind != TypeKind.INT:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"condition must be `Bool`, got `{cond_type}`",
                    expr.line, expr.column
                )

        then_type = self._check_block(expr.then_branch)

        if expr.else_branch:
            else_type = self._check_block(expr.else_branch)

            # If both branches have values, they must match
            if then_type and else_type and not self._types_compatible(then_type, else_type):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`if` and `else` branches have incompatible types: `{then_type}` vs `{else_type}`",
                    expr.line, expr.column
                )

            # If one branch is None literal, the result type is Optional<other>
            if then_type and else_type:
                if else_type.is_none_literal():
                    # else is None, result is Optional<then_type>
                    result_type = then_type.wrap_optional()
                    # Annotate the None literal with its resolved type
                    self._annotate_none_in_block(expr.else_branch, result_type)
                    return result_type
                if then_type.is_none_literal():
                    # then is None, result is Optional<else_type>
                    result_type = else_type.wrap_optional()
                    # Annotate the None literal with its resolved type
                    self._annotate_none_in_block(expr.then_branch, result_type)
                    return result_type

            return then_type or else_type
        else:
            return then_type

    def _check_if_let_expr(self, expr: IfLetExpr) -> Optional[SawType]:
        """Check an if let/var expression for optional binding."""
        # Check the optional expression
        optional_type = self._check_expression(expr.optional_expr)

        if optional_type is None:
            return None

        # Must be an optional type
        if optional_type.kind != TypeKind.OPTIONAL:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"'if let' requires an optional type, got `{optional_type}`",
                expr.line, expr.column
            )
            return None

        # For 'if var', the source optional must be mutable (we'd need to track this)
        # For now, we'll allow it - the reference semantics will be enforced at codegen

        # Get the unwrapped type
        inner_type = optional_type.inner_type
        if inner_type is None:
            # None literal with unknown type - treat as void or error
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot determine type of bound variable from None literal",
                expr.line, expr.column
            )
            return None

        # Create new scope for then branch with the bound variable
        old_scope = self.current_scope
        self.current_scope = Scope(parent=old_scope)
        self.current_scope.define(
            expr.name,
            VariableInfo(inner_type, expr.mutable, expr.line, expr.column)
        )

        then_type = self._check_block(expr.then_branch)

        self.current_scope = old_scope

        # Check else branch if present
        else_type = None
        if expr.else_branch:
            else_type = self._check_block(expr.else_branch)

            # If both branches have values, they must match
            if then_type and else_type and not self._types_compatible(then_type, else_type):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`if let` branches have incompatible types: `{then_type}` vs `{else_type}`",
                    expr.line, expr.column
                )

            return then_type or else_type
        else:
            return then_type

    def _check_tuple_literal(self, expr: TupleLiteral) -> Optional[SawType]:
        """Check a tuple literal."""
        element_types = []
        for element in expr.elements:
            elem_type = self._check_expression(element)
            if elem_type is None:
                return None
            element_types.append(elem_type)
        return SawType(TypeKind.TUPLE, element_types=element_types)

    def _check_tuple_index(self, expr: TupleIndex) -> Optional[SawType]:
        """Check tuple indexing."""
        tuple_type = self._check_expression(expr.tuple_expr)
        if tuple_type is None:
            return None

        if tuple_type.kind != TypeKind.TUPLE:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot index into non-tuple type `{tuple_type}`",
                expr.line, expr.column
            )
            return None

        if tuple_type.element_types is None:
            return None

        if expr.index < 0 or expr.index >= len(tuple_type.element_types):
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"tuple index {expr.index} out of range for tuple with {len(tuple_type.element_types)} elements",
                expr.line, expr.column
            )
            return None

        return tuple_type.element_types[expr.index]

    def _check_array_literal(self, expr: ArrayLiteral) -> Optional[SawType]:
        """Check an array literal and infer its type."""
        if len(expr.elements) == 0:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                "cannot infer type of empty array literal; use explicit type annotation",
                expr.line, expr.column
            )
            return None

        # Check first element to get the expected type
        first_type = self._check_expression(expr.elements[0])
        if first_type is None:
            return None

        # Check all other elements match the first type
        for i, element in enumerate(expr.elements[1:], start=1):
            elem_type = self._check_expression(element)
            if elem_type is None:
                return None
            if not self._types_compatible(elem_type, first_type):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"array element {i} has type `{elem_type}`, expected `{first_type}`",
                    element.line, element.column
                )
                return None

        return SawType(
            TypeKind.ARRAY,
            array_element_type=first_type,
            array_size=len(expr.elements)
        )

    def _check_array_index(self, expr: ArrayIndex) -> Optional[SawType]:
        """Check array or tuple indexing with [index] syntax."""
        container_type = self._check_expression(expr.array_expr)
        if container_type is None:
            return None

        # Check that index is an integer
        index_type = self._check_expression(expr.index)
        if index_type is None:
            return None

        index_underlying = self._get_underlying_type(index_type)
        if index_underlying.kind != TypeKind.INT:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"index must be Int, got `{index_type}`",
                expr.index.line, expr.index.column
            )
            return None

        # Handle array indexing
        if container_type.kind == TypeKind.ARRAY:
            return container_type.array_element_type

        # Handle tuple indexing (requires compile-time constant index)
        elif container_type.kind == TypeKind.TUPLE:
            # For tuples, index must be a literal integer (compile-time known)
            if not isinstance(expr.index, IntLiteral):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    "tuple index must be a compile-time constant",
                    expr.index.line, expr.index.column
                )
                return None

            index = expr.index.value
            if container_type.element_types is None:
                return None

            if index < 0 or index >= len(container_type.element_types):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"tuple index {index} out of range for tuple with {len(container_type.element_types)} elements",
                    expr.line, expr.column
                )
                return None

            return container_type.element_types[index]

        # Handle pointer indexing: ptr[i] returns the pointee type
        elif container_type.kind == TypeKind.POINTER:
            return container_type.inner_type

        else:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot index into type `{container_type}`",
                expr.line, expr.column
            )
            return None

    def _check_member_access(self, expr: MemberAccess) -> Optional[SawType]:
        """Check member access for struct fields or enum variant access."""
        # Special case: EnumName.VariantName (simple variant with no associated values)
        # This is parsed as MemberAccess where object is an Identifier
        if isinstance(expr.object, Identifier):
            # Check if it's an enum name
            if expr.object.name in self.enums:
                enum_info = self.enums[expr.object.name]

                # Check type arguments for generic enums
                type_args = expr.object.type_args
                if enum_info.type_params:
                    if not type_args:
                        self.reporter.error(
                            ErrorKind.TYPE_MISMATCH,
                            f"generic enum `{expr.object.name}` requires type arguments",
                            expr.line, expr.column,
                            hint=f"use `{expr.object.name}<...>.{expr.member}`"
                        )
                    elif len(type_args) != len(enum_info.type_params):
                        self.reporter.error(
                            ErrorKind.WRONG_ARGUMENT_COUNT,
                            f"expected {len(enum_info.type_params)} type argument(s), got {len(type_args)}",
                            expr.line, expr.column
                        )

                # Check if the member is a valid variant
                if expr.member in enum_info.variants:
                    variant_params = enum_info.variants[expr.member]
                    # Only simple variants (no associated values) can be accessed this way
                    if len(variant_params) == 0:
                        # This is a simple enum variant
                        return SawType(TypeKind.ENUM, enum_name=expr.object.name, type_args=type_args)
                    else:
                        self.reporter.error(
                            ErrorKind.TYPE_MISMATCH,
                            f"variant `{expr.member}` has associated values and must be called like `{expr.object.name}.{expr.member}(...)`",
                            expr.line, expr.column
                        )
                        return None
                else:
                    self.reporter.error(
                        ErrorKind.UNDEFINED_VARIABLE,
                        f"enum `{expr.object.name}` has no variant `{expr.member}`",
                        expr.line, expr.column
                    )
                    return None

        obj_type = self._check_expression(expr.object)
        if obj_type is None:
            return None

        if obj_type.kind != TypeKind.STRUCT:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot access member of non-struct type `{obj_type}`",
                expr.line, expr.column
            )
            return None

        if obj_type.struct_name is None:
            return None

        struct_info = self.structs.get(obj_type.struct_name)
        if struct_info is None:
            # This shouldn't happen if type checking is working correctly
            return None

        if expr.member not in struct_info.fields:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"struct `{obj_type.struct_name}` has no field `{expr.member}`",
                expr.line, expr.column,
                hint=f"available fields: {', '.join(struct_info.field_order)}"
            )
            return None

        return struct_info.fields[expr.member]

    def _check_struct_init(self, expr: StructInit) -> Optional[SawType]:
        """Check struct initialization with parameter-based resolution."""
        # Check if struct exists
        struct_info = self.structs.get(expr.struct_name)
        if struct_info is None:
            self.reporter.error(
                ErrorKind.UNDEFINED_VARIABLE,  # Could add UNDEFINED_STRUCT
                f"undefined struct `{expr.struct_name}`",
                expr.line, expr.column
            )
            return None

        # Build type mapping for generic structs
        type_mapping: Dict[str, SawType] = {}
        if struct_info.type_params:
            if not expr.type_args:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"generic struct `{expr.struct_name}` requires type arguments",
                    expr.line, expr.column,
                    hint=f"use `{expr.struct_name}<...>(...)`"
                )
            elif len(expr.type_args) != len(struct_info.type_params):
                self.reporter.error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"expected {len(struct_info.type_params)} type argument(s), got {len(expr.type_args)}",
                    expr.line, expr.column
                )
            else:
                # Create type mapping: T -> Int, U -> String, etc.
                for type_param, type_arg in zip(struct_info.type_params, expr.type_args):
                    type_mapping[type_param.name] = type_arg

        # Get provided parameter names
        provided_params = {field_name for field_name, _ in expr.field_inits}

        # Try to match against field initialization
        field_names = set(struct_info.fields.keys())
        matches_fields = provided_params == field_names

        # Try to match against custom init methods
        matching_inits = []
        for method_name, method_info in struct_info.methods.items():
            if method_info.is_init:
                init_param_names = set(method_info.param_names)
                if provided_params == init_param_names:
                    matching_inits.append(method_info)

        # Resolve which initialization to use
        total_matches = (1 if matches_fields else 0) + len(matching_inits)

        if total_matches == 0:
            # No match found
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"no matching initializer for `{expr.struct_name}` with parameters: {', '.join(sorted(provided_params))}",
                expr.line, expr.column,
                hint=f"field init expects: {', '.join(sorted(field_names))}" +
                     (f"; available init methods: {[m.param_names for m in struct_info.methods.values() if m.is_init]}" if any(m.is_init for m in struct_info.methods.values()) else "")
            )
            return SawType(TypeKind.STRUCT, struct_name=expr.struct_name, type_args=expr.type_args)

        elif total_matches > 1:
            # Ambiguous
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"ambiguous initializer for `{expr.struct_name}` - matches both field initialization and custom init",
                expr.line, expr.column,
                hint="use different parameter names in init method to disambiguate"
            )
            return SawType(TypeKind.STRUCT, struct_name=expr.struct_name, type_args=expr.type_args)

        # Exactly one match - resolve it
        if matches_fields:
            # Field initialization
            expr.resolved_init_params = None

            # Check field types (with type substitution for generics)
            for field_name, field_value in expr.field_inits:
                expected_type = struct_info.fields[field_name]
                # Substitute type parameters with concrete types
                if type_mapping:
                    expected_type = expected_type.substitute(type_mapping)
                actual_type = self._check_expression(field_value)
                # Annotate None literals with expected type for codegen
                if expected_type.kind == TypeKind.OPTIONAL and isinstance(field_value, NoneLiteral):
                    field_value.resolved_type = expected_type
                if actual_type and not self._types_compatible(actual_type, expected_type):
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"field `{field_name}` expects type `{expected_type}` but got `{actual_type}`",
                        expr.line, expr.column
                    )
        else:
            # Custom init method
            method_info = matching_inits[0]
            expr.resolved_init_params = method_info.param_names

            # Check argument types (with type substitution for generics)
            for field_name, field_value in expr.field_inits:
                # Find parameter index
                param_idx = method_info.param_names.index(field_name)
                expected_type = method_info.param_types[param_idx]
                # Substitute type parameters with concrete types
                if type_mapping:
                    expected_type = expected_type.substitute(type_mapping)
                actual_type = self._check_expression(field_value)
                if actual_type and not self._types_compatible(actual_type, expected_type):
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"parameter `{field_name}` expects type `{expected_type}` but got `{actual_type}`",
                        expr.line, expr.column
                    )

        return SawType(TypeKind.STRUCT, struct_name=expr.struct_name, type_args=expr.type_args)

    def _check_none_literal(self, expr: NoneLiteral) -> Optional[SawType]:
        """Check None literal - returns a special 'None' type that can unify with any T?."""
        # None has a special type that's compatible with any optional
        return SawType(TypeKind.OPTIONAL, inner_type=None)

    def _annotate_none_in_block(self, block: Block, resolved_type: SawType):
        """Annotate any NoneLiteral in the block's final expression with its resolved type."""
        if block.final_expr is not None:
            self._annotate_none_in_expr(block.final_expr, resolved_type)

    def _annotate_none_in_expr(self, expr: Expression, resolved_type: SawType):
        """Recursively find and annotate NoneLiteral nodes with their resolved type."""
        if isinstance(expr, NoneLiteral):
            expr.resolved_type = resolved_type
        elif isinstance(expr, IfExpr):
            # Check both branches of if expressions
            if expr.then_branch.final_expr:
                self._annotate_none_in_expr(expr.then_branch.final_expr, resolved_type)
            if expr.else_branch and expr.else_branch.final_expr:
                self._annotate_none_in_expr(expr.else_branch.final_expr, resolved_type)

    def _check_force_unwrap(self, expr: ForceUnwrap) -> Optional[SawType]:
        """Check force unwrap: expr! - unwraps T? to T."""
        inner_type = self._check_expression(expr.expr)
        if inner_type is None:
            return None

        # Handle distinct optional types (e.g., type OptInt = Int?)
        if inner_type.kind == TypeKind.STRUCT and inner_type.struct_name in self.type_aliases:
            underlying = self._get_underlying_type(inner_type)
            if underlying.kind == TypeKind.OPTIONAL:
                return underlying.inner_type

        if inner_type.kind != TypeKind.OPTIONAL:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot force unwrap non-optional type `{inner_type}`",
                expr.line, expr.column
            )
            return inner_type  # Return original type to continue checking

        return inner_type.inner_type

    def _check_nil_coalesce(self, expr: NilCoalesce) -> Optional[SawType]:
        """Check nil coalescing: expr ?? default - returns T."""
        opt_type = self._check_expression(expr.expr)
        default_type = self._check_expression(expr.default)

        if opt_type is None or default_type is None:
            return default_type

        if opt_type.kind != TypeKind.OPTIONAL:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"left side of `??` must be optional, got `{opt_type}`",
                expr.line, expr.column
            )
            return opt_type

        # Check that the inner type matches the default type
        if opt_type.inner_type and not self._types_compatible(opt_type.inner_type, default_type):
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"optional inner type `{opt_type.inner_type}` does not match default type `{default_type}`",
                expr.line, expr.column
            )

        return default_type

    def _check_optional_chain(self, expr: OptionalChain) -> Optional[SawType]:
        """Check optional chaining: expr?.member - returns U?."""
        opt_type = self._check_expression(expr.expr)
        if opt_type is None:
            return None

        if opt_type.kind != TypeKind.OPTIONAL:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot use optional chaining on non-optional type `{opt_type}`",
                expr.line, expr.column
            )
            return None

        inner_type = opt_type.inner_type
        if inner_type is None:
            return None

        # Check that inner type is a struct
        if inner_type.kind != TypeKind.STRUCT:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot access member of non-struct type `{inner_type}`",
                expr.line, expr.column
            )
            return None

        # Look up the field
        struct_info = self.structs.get(inner_type.struct_name)
        if struct_info is None:
            return None

        if expr.member not in struct_info.fields:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"struct `{inner_type.struct_name}` has no field `{expr.member}`",
                expr.line, expr.column,
                hint=f"available fields: {', '.join(struct_info.field_order)}"
            )
            return None

        # Return the field type wrapped in optional
        field_type = struct_info.fields[expr.member]
        return SawType(TypeKind.OPTIONAL, inner_type=field_type)

    def _check_method_call(self, expr: MethodCall) -> Optional[SawType]:
        """Check a method call or enum initialization: object.method(args) or Enum.Variant(args).

        The parser creates MethodCall for both cases. This method disambiguates based on
        whether the object refers to an enum type.
        """
        # Check if this is actually an enum initialization
        # This happens when object is an Identifier that matches an enum name
        if isinstance(expr.object, Identifier) and expr.object.name in self.enums:
            # Convert to EnumInit and check it
            # Pass type_args from the Identifier (for generic enums like Option<Int>.Some)
            enum_init = EnumInit(
                enum_name=expr.object.name,
                variant_name=expr.method_name,
                arguments=expr.arguments,
                type_args=expr.object.type_args,
                line=expr.line,
                column=expr.column
            )
            return self._check_enum_init(enum_init)

        # Otherwise, it's a method call - check the object type
        obj_type = self._check_expression(expr.object)
        if obj_type is None:
            return None

        # Must be a struct type
        if obj_type.kind != TypeKind.STRUCT:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot call method on non-struct type `{obj_type}`",
                expr.line, expr.column
            )
            return None

        if obj_type.struct_name is None:
            return None

        struct_info = self.structs.get(obj_type.struct_name)
        if struct_info is None:
            return None

        # Build type substitution map for generic structs
        # e.g., for Vector<Int>, map T -> Int
        type_subst: Dict[str, SawType] = {}
        if struct_info.type_params and obj_type.type_args:
            for type_param, type_arg in zip(struct_info.type_params, obj_type.type_args):
                type_subst[type_param.name] = type_arg

        # Look up method
        if expr.method_name not in struct_info.methods:
            self.reporter.error(
                ErrorKind.UNDEFINED_FUNCTION,
                f"struct `{obj_type.struct_name}` has no method `{expr.method_name}`",
                expr.line, expr.column,
                hint=f"available methods: {', '.join(struct_info.methods.keys())}" if struct_info.methods else "no methods defined"
            )
            return None

        method_info = struct_info.methods[expr.method_name]

        # Disallow manual deinit calls - deinit is called automatically by the compiler
        if expr.method_name == "deinit":
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot call `deinit` manually; it is called automatically when the value goes out of scope",
                expr.line, expr.column,
                hint="use a nested scope or `move` to transfer ownership if you need early cleanup"
            )
            return None

        # Check argument count (excluding 'self' which is implicit in method calls)
        expected_arg_count = len(method_info.param_types) - 1  # -1 for self
        if method_info.is_init:
            expected_arg_count = len(method_info.param_types)  # init has no self

        if len(expr.arguments) != expected_arg_count:
            self.reporter.error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"method `{expr.method_name}` takes {expected_arg_count} argument(s), "
                f"but {len(expr.arguments)} were given",
                expr.line, expr.column
            )
            return method_info.return_type

        # Check argument types (skip first param which is self for non-init methods)
        # Arguments are now Argument objects with .value and optional .name
        param_offset = 1 if not method_info.is_init else 0
        for i, arg in enumerate(expr.arguments):
            arg_type = self._check_expression(arg.value)
            expected_type = method_info.param_types[i + param_offset]
            # Substitute type parameters for generic structs
            if type_subst:
                expected_type = expected_type.substitute(type_subst)
            if arg_type and not self._types_compatible(arg_type, expected_type):
                param_name = method_info.param_names[i + param_offset]
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument `{param_name}` expects `{expected_type}` but got `{arg_type}`",
                    arg.value.line, arg.value.column
                )

        # Substitute type parameters in return type
        return_type = method_info.return_type
        if type_subst:
            return_type = return_type.substitute(type_subst)
        return return_type

    def _check_self_expr(self, expr: SelfExpr) -> Optional[SawType]:
        """Check 'self' keyword usage."""
        if self.current_method is None:
            self.reporter.error(
                ErrorKind.UNDEFINED_VARIABLE,
                "'self' can only be used inside methods",
                expr.line, expr.column
            )
            return None

        # Look up 'self' in current scope (it's a parameter)
        var_info = self.current_scope.lookup("self")
        if not var_info:
            self.reporter.error(
                ErrorKind.UNDEFINED_VARIABLE,
                "'self' not found in method scope",
                expr.line, expr.column
            )
            return None

        return var_info.type

    def _check_enum_init(self, expr: EnumInit) -> Optional[SawType]:
        """Check enum variant initialization.

        Supports both named arguments (value: 42) and positional arguments (42).
        Also supports generic enums like Option<Int>.Some(value: 42).
        """
        # Verify enum exists
        if expr.enum_name not in self.enums:
            self.reporter.error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"undefined enum `{expr.enum_name}`",
                expr.line, expr.column
            )
            return None

        enum_info = self.enums[expr.enum_name]

        # Build type mapping for generic enums
        type_mapping: Dict[str, SawType] = {}
        if enum_info.type_params:
            if not expr.type_args:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"generic enum `{expr.enum_name}` requires type arguments",
                    expr.line, expr.column,
                    hint=f"use `{expr.enum_name}<...>.{expr.variant_name}(...)`"
                )
            elif len(expr.type_args) != len(enum_info.type_params):
                self.reporter.error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"expected {len(enum_info.type_params)} type argument(s), got {len(expr.type_args)}",
                    expr.line, expr.column
                )
            else:
                # Create type mapping: T -> Int, etc.
                for type_param, type_arg in zip(enum_info.type_params, expr.type_args):
                    type_mapping[type_param.name] = type_arg

        # Verify variant exists
        if expr.variant_name not in enum_info.variants:
            self.reporter.error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"enum `{expr.enum_name}` has no variant `{expr.variant_name}`",
                expr.line, expr.column
            )
            return None

        expected_params = enum_info.variants[expr.variant_name]

        # Apply type substitution to expected param types for generic enums
        if type_mapping:
            expected_params = [(name, typ.substitute(type_mapping))
                               for name, typ in expected_params]

        # Check argument count
        if len(expr.arguments) != len(expected_params):
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"variant `{expr.variant_name}` expects {len(expected_params)} arguments, got {len(expr.arguments)}",
                expr.line, expr.column
            )
            return None

        # Arguments are now Argument objects with .value and optional .name
        # Support both named and positional arguments
        expected_dict = {name: typ for name, typ in expected_params}
        expected_list = expected_params  # [(name, type), ...]

        for i, arg in enumerate(expr.arguments):
            if arg.is_named:
                # Named argument - look up by name
                if arg.name not in expected_dict:
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"variant `{expr.variant_name}` has no parameter named `{arg.name}`",
                        expr.line, expr.column
                    )
                    continue

                arg_type = self._check_expression(arg.value)
                expected_type = expected_dict[arg.name]
                if arg_type and not self._types_compatible(arg_type, expected_type):
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"expected type `{expected_type}` for parameter `{arg.name}`, got `{arg_type}`",
                        arg.value.line, arg.value.column
                    )
            else:
                # Positional argument - match by position
                if i >= len(expected_list):
                    continue  # Already reported count mismatch

                param_name, expected_type = expected_list[i]
                arg_type = self._check_expression(arg.value)
                if arg_type and not self._types_compatible(arg_type, expected_type):
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"expected type `{expected_type}` for parameter `{param_name}`, got `{arg_type}`",
                        arg.value.line, arg.value.column
                    )

        # Return enum type with type_args for generic enums
        return SawType(TypeKind.ENUM, enum_name=expr.enum_name, type_args=expr.type_args)

    def _check_match_expr(self, expr: MatchExpr) -> Optional[SawType]:
        """Check match expression."""
        # Check matched expression
        matched_type = self._check_expression(expr.matched_expr)
        if matched_type is None:
            return None

        # Verify it's an enum type
        if matched_type.kind != TypeKind.ENUM or matched_type.enum_name is None:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"match expression requires an enum type, got `{matched_type}`",
                expr.line, expr.column
            )
            return None

        enum_info = self.enums.get(matched_type.enum_name)
        if enum_info is None:
            return None  # Error already reported

        # Build type mapping for generic enums
        type_mapping: Dict[str, SawType] = {}
        if enum_info.type_params and matched_type.type_args:
            for type_param, type_arg in zip(enum_info.type_params, matched_type.type_args):
                type_mapping[type_param.name] = type_arg

        # Type check each arm and track matched variants for exhaustiveness
        arm_types = []
        matched_variants = set()
        has_wildcard = False

        for arm in expr.arms:
            # Check for wildcard pattern
            if arm.variant_name == "_":
                has_wildcard = True
                # Wildcard has no bindings and matches everything
                if arm.bindings:
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        "wildcard pattern `_` cannot have bindings",
                        arm.line, arm.column
                    )
                # Type check arm body
                if isinstance(arm.body, Block):
                    arm_type = self._check_block(arm.body)
                else:
                    arm_type = self._check_expression(arm.body)
                arm_types.append(arm_type)
                continue

            # Verify variant exists
            if arm.variant_name not in enum_info.variants:
                self.reporter.error(
                    ErrorKind.UNDEFINED_VARIABLE,
                    f"enum `{matched_type.enum_name}` has no variant `{arm.variant_name}`",
                    arm.line, arm.column
                )
                continue

            matched_variants.add(arm.variant_name)
            variant_params = enum_info.variants[arm.variant_name]

            # Apply type substitution for generic enums
            if type_mapping:
                variant_params = [(name, typ.substitute(type_mapping))
                                  for name, typ in variant_params]

            # Check binding count
            if len(arm.bindings) != len(variant_params):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"variant `{arm.variant_name}` has {len(variant_params)} associated values, got {len(arm.bindings)} bindings",
                    arm.line, arm.column
                )
                continue

            # Create new scope for arm body with bindings
            old_scope = self.current_scope
            self.current_scope = Scope(parent=old_scope)

            # Add bindings to scope (with substituted types for generic enums)
            for binding_name, (_, param_type) in zip(arm.bindings, variant_params):
                var_info = VariableInfo(
                    type=param_type,
                    mutable=False,  # Bindings are immutable by default
                    line=arm.line,
                    column=arm.column
                )
                if not self.current_scope.define(binding_name, var_info):
                    self.reporter.error(
                        ErrorKind.DUPLICATE_VARIABLE,
                        f"binding `{binding_name}` is already defined in this scope",
                        arm.line, arm.column
                    )

            # Type check arm body
            if isinstance(arm.body, Block):
                arm_type = self._check_block(arm.body)
            else:
                arm_type = self._check_expression(arm.body)

            arm_types.append(arm_type)

            # Restore scope
            self.current_scope = old_scope

        # Check exhaustiveness - error if not all variants are covered
        if not has_wildcard:
            all_variants = set(enum_info.variants.keys())
            missing_variants = all_variants - matched_variants
            if missing_variants:
                missing_list = ", ".join(f"`{v}`" for v in sorted(missing_variants))
                self.reporter.error(
                    ErrorKind.NON_EXHAUSTIVE_MATCH,
                    f"match is not exhaustive, missing variants: {missing_list}",
                    expr.line, expr.column,
                    hint="add missing cases or use `case _ ->` as a default"
                )

        # Verify all arms have compatible return types
        if not arm_types:
            return None

        result_type = arm_types[0]
        for arm_type in arm_types[1:]:
            if not self._types_compatible(result_type, arm_type):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"match arms have incompatible types: `{result_type}` and `{arm_type}`",
                    expr.line, expr.column
                )
                return None

        return result_type

    def _check_closure(self, expr: ClosureExpr, expected_type: Optional[SawType] = None) -> Optional[SawType]:
        """Type check a closure expression.

        If expected_type is provided (e.g., from parameter type hint), use it to
        infer parameter types for unannotated parameters.
        """
        # Create new scope for closure body
        outer_scope = self.current_scope
        self.current_scope = Scope(parent=outer_scope)

        param_types = []

        if expr.parameters:
            # Named parameters
            for i, param in enumerate(expr.parameters):
                if param.type_annotation:
                    param_type = self._resolve_type(param.type_annotation)
                elif expected_type and expected_type.kind == TypeKind.FUNCTION:
                    # Infer from expected type
                    expected_params = expected_type.param_types or []
                    if i < len(expected_params):
                        param_type = expected_params[i]
                    else:
                        self.reporter.error(
                            ErrorKind.TYPE_MISMATCH,
                            f"Closure has more parameters than expected function type",
                            param.line, param.column
                        )
                        param_type = SawType(TypeKind.INT)  # Fallback
                else:
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"Cannot infer type for closure parameter `{param.name}`. Add type annotation: `{param.name}: Type`",
                        param.line, param.column
                    )
                    param_type = SawType(TypeKind.INT)  # Fallback

                param_types.append(param_type)
                self.current_scope.define(param.name, VariableInfo(param_type, False, param.line, param.column))

        elif expr.shorthand_param_count > 0:
            # Shorthand parameters $0, $1, ...
            for i in range(expr.shorthand_param_count):
                if expected_type and expected_type.kind == TypeKind.FUNCTION:
                    expected_params = expected_type.param_types or []
                    if i < len(expected_params):
                        param_type = expected_params[i]
                    else:
                        self.reporter.error(
                            ErrorKind.TYPE_MISMATCH,
                            f"Closure uses `${i}` but expected function type only has {len(expected_params)} parameters",
                            expr.line, expr.column
                        )
                        param_type = SawType(TypeKind.INT)
                else:
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"Cannot infer type for shorthand parameter `${i}`. Use named parameters with type annotations.",
                        expr.line, expr.column
                    )
                    param_type = SawType(TypeKind.INT)

                param_types.append(param_type)
                self.current_scope.define(f"${i}", VariableInfo(param_type, False, expr.line, expr.column))

        # Check body and get return type
        return_type = self._check_block(expr.body)
        if return_type is None:
            return_type = SawType(TypeKind.VOID)

        # Analyze captures (variables from outer scope used in body)
        captures = self._analyze_closure_captures(expr.body, outer_scope)
        expr.captures = captures

        # Restore scope
        self.current_scope = outer_scope

        return SawType(TypeKind.FUNCTION, param_types=param_types, func_return_type=return_type)

    def _analyze_closure_captures(self, body: Block, outer_scope: 'Scope') -> List[str]:
        """Find all variables from outer scope that are used in the closure body."""
        captures = []
        used_names = set()

        def collect_names(expr):
            if expr is None:
                return
            if isinstance(expr, Identifier):
                used_names.add(expr.name)
            elif isinstance(expr, BinaryOp):
                collect_names(expr.left)
                collect_names(expr.right)
            elif isinstance(expr, UnaryOp):
                collect_names(expr.operand)
            elif isinstance(expr, FunctionCall):
                for arg in expr.arguments:
                    collect_names(arg.value)
            elif isinstance(expr, MethodCall):
                collect_names(expr.object)
                for arg in expr.arguments:
                    collect_names(arg.value)
            elif isinstance(expr, IfExpr):
                collect_names(expr.condition)
                collect_block(expr.then_branch)
                if expr.else_branch:
                    collect_block(expr.else_branch)
            elif isinstance(expr, TupleLiteral):
                for elem in expr.elements:
                    collect_names(elem)
            elif isinstance(expr, ArrayLiteral):
                for elem in expr.elements:
                    collect_names(elem)
            elif isinstance(expr, ArrayIndex):
                collect_names(expr.array_expr)
                collect_names(expr.index)
            elif isinstance(expr, MemberAccess):
                collect_names(expr.object)
            elif isinstance(expr, ForceUnwrap):
                collect_names(expr.expr)
            elif isinstance(expr, NilCoalesce):
                collect_names(expr.expr)
                collect_names(expr.default)
            elif isinstance(expr, OptionalChain):
                collect_names(expr.expr)
            elif isinstance(expr, ClosureExpr):
                # Don't recurse into nested closures - they have their own captures
                pass

        def collect_block(block):
            if block is None:
                return
            for stmt in block.statements:
                if isinstance(stmt, ExpressionStatement):
                    collect_names(stmt.expression)
                elif isinstance(stmt, LetStatement):
                    collect_names(stmt.value)
                elif isinstance(stmt, AssignStatement):
                    collect_names(stmt.value)
                    collect_names(stmt.target)
                elif isinstance(stmt, ReturnStatement):
                    if stmt.value:
                        collect_names(stmt.value)
            if block.final_expr:
                collect_names(block.final_expr)

        collect_block(body)

        # Filter to only variables from outer scope
        for name in used_names:
            var_info = outer_scope.lookup(name)
            if var_info:
                captures.append(name)

        return captures

    def _resolve_type(self, saw_type: SawType) -> SawType:
        """Resolve user-defined types (ENUMs parsed as STRUCT). Does NOT resolve type aliases."""
        if saw_type.kind == TypeKind.STRUCT and saw_type.struct_name:
            # Check if this is actually an enum (NOT a type alias - those stay as STRUCT)
            if saw_type.struct_name in self.enums:
                return SawType(TypeKind.ENUM, enum_name=saw_type.struct_name)
            # Recursively resolve type args
            if saw_type.type_args:
                resolved_args = [self._resolve_type(t) for t in saw_type.type_args]
                return SawType(TypeKind.STRUCT, struct_name=saw_type.struct_name, type_args=resolved_args)
        elif saw_type.kind == TypeKind.OPTIONAL and saw_type.inner_type:
            # Recursively resolve optional inner types
            resolved_inner = self._resolve_type(saw_type.inner_type)
            return SawType(TypeKind.OPTIONAL, inner_type=resolved_inner)
        elif saw_type.kind == TypeKind.TUPLE and saw_type.element_types:
            # Recursively resolve tuple element types
            resolved_elements = [self._resolve_type(t) for t in saw_type.element_types]
            return SawType(TypeKind.TUPLE, element_types=resolved_elements)
        elif saw_type.kind == TypeKind.ENUM and saw_type.type_args:
            # Recursively resolve enum type args
            resolved_args = [self._resolve_type(t) for t in saw_type.type_args]
            return SawType(TypeKind.ENUM, enum_name=saw_type.enum_name, type_args=resolved_args)
        elif saw_type.kind == TypeKind.FUNCTION:
            # Recursively resolve function param and return types
            resolved_params = [self._resolve_type(t) for t in (saw_type.param_types or [])]
            resolved_return = self._resolve_type(saw_type.func_return_type) if saw_type.func_return_type else None
            return SawType(TypeKind.FUNCTION, param_types=resolved_params, func_return_type=resolved_return)
        return saw_type

    def _get_underlying_type(self, saw_type: SawType) -> SawType:
        """Get the underlying primitive type for a type (resolves type aliases).
        Used for checking if operations are valid on distinct types."""
        if saw_type.kind == TypeKind.STRUCT and saw_type.struct_name:
            # Resolve type alias to underlying type
            if saw_type.struct_name in self.type_aliases:
                return self._get_underlying_type(self.type_aliases[saw_type.struct_name])
        elif saw_type.kind == TypeKind.OPTIONAL and saw_type.inner_type:
            resolved_inner = self._get_underlying_type(saw_type.inner_type)
            return SawType(TypeKind.OPTIONAL, inner_type=resolved_inner)
        return saw_type

    def _types_compatible(self, a: Optional[SawType], b: Optional[SawType],
                          allow_literal_to_distinct: bool = False) -> bool:
        """Check if two types are compatible.

        Args:
            a: The source type (what we have)
            b: The target type (what we expect)
            allow_literal_to_distinct: If True, allows primitive types to initialize distinct types.
                                       Only pass True for let/var initialization context.
        """
        if a is None or b is None:
            return True  # Assume compatible if we couldn't determine types

        # None literal is compatible with any optional
        if a.is_none_literal() and b.is_optional():
            return True
        if b.is_none_literal() and a.is_optional():
            return True

        # None literal is compatible with any type that can be wrapped in optional
        # This allows: if cond { value } else { None } to work
        if b.is_none_literal() or a.is_none_literal():
            return True

        # Allow implicit wrapping: T is compatible with T?
        if b.is_optional() and not a.is_optional():
            if self._types_compatible(a, b.unwrap_optional(), allow_literal_to_distinct):
                return True

        # Check if b is a distinct type (STRUCT with name in type_aliases)
        if b.is_struct() and b.struct_name in self.type_aliases:
            # Allow primitive types to initialize distinct type wrappers
            # Only in initialization context (allow_literal_to_distinct=True)
            if allow_literal_to_distinct:
                underlying = self._get_underlying_type(b)
                if a.is_primitive():
                    if a.kind == underlying.kind:
                        return True
                    # Also handle distinct optional types: OptInt = Int?
                    # Allow Int to be implicitly wrapped into OptInt
                    if underlying.is_optional() and underlying.inner_type:
                        if a.kind == underlying.inner_type.kind:
                            return True
            # Always allow if 'a' is the same distinct type
            if a.is_struct() and a.struct_name == b.struct_name:
                return True

        # Allow integer literal (INT) to be compatible with any integer type
        # This enables: let x: Int8 = 42
        int_kinds = {TypeKind.INT, TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
                     TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64}
        if a.kind in int_kinds and b.kind in int_kinds:
            return True

        # Allow String to be passed where UnsafePointer<Int8> is expected (for FFI)
        # Saw strings are null-terminated C strings internally
        if (a.kind == TypeKind.STRING and
            b.kind == TypeKind.POINTER and
            b.inner_type and b.inner_type.kind == TypeKind.INT8):
            return True

        if a.kind != b.kind:
            return False

        # For tuple types, check element types match
        if a.is_tuple():
            if a.element_types is None or b.element_types is None:
                return True
            if len(a.element_types) != len(b.element_types):
                return False
            return all(self._types_compatible(at, bt)
                      for at, bt in zip(a.element_types, b.element_types))

        # For struct types, check struct names match
        if a.is_struct():
            if a.struct_name == b.struct_name:
                return True
            # Check if b is an interface that a conforms to
            if b.struct_name in self.interfaces:
                # a must be a struct that conforms to interface b
                if a.struct_name in self.type_conformances:
                    return b.struct_name in self.type_conformances[a.struct_name]
            return False

        # For enum types, check enum names match
        if a.is_enum():
            return a.enum_name == b.enum_name

        # For optional types, check inner types match
        if a.is_optional():
            if a.inner_type is None or b.inner_type is None:
                return True
            return self._types_compatible(a.inner_type, b.inner_type)

        # For function types, check param types and return type match
        if a.is_function():
            a_params = a.param_types or []
            b_params = b.param_types or []
            if len(a_params) != len(b_params):
                return False
            for ap, bp in zip(a_params, b_params):
                if not self._types_compatible(ap, bp):
                    return False
            return self._types_compatible(a.func_return_type, b.func_return_type)

        return True

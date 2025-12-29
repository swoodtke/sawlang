"""
Saw Language Code Generator
Generates LLVM IR from the AST using llvmlite.
"""

from typing import Optional, List
from llvmlite import ir, binding
from ast_nodes import (
    Program, Function, Block, Statement, Expression,
    LetStatement, AssignStatement, ReturnStatement, ExpressionStatement,
    WhileExpr, BreakStatement, ContinueStatement, ForLoop, RangeExpr,
    IntLiteral, FloatLiteral, BoolLiteral, StringLiteral, StringInterpolation, Identifier,
    BinaryOp, UnaryOp, MoveExpr, CastExpr, FunctionCall, IfExpr, IfLetExpr,
    TupleLiteral, TupleIndex, ArrayLiteral, ArrayIndex,
    MemberAccess, StructInit,
    NoneLiteral, ForceUnwrap, NilCoalesce, OptionalChain,
    TryExpr, TryCatchExpr,
    GuardLetStatement,
    Struct, StructField,
    Enum, EnumVariant, EnumInit, MatchExpr, MatchArm,
    Extension, Method, MethodCall, SelfExpr,
    SawType, TypeKind, Argument, TypeParameter, TypeDefinition,
    ExternFunction, ExternBlock,
    ClosureExpr
)
from namespace import Namespace
from .types import TypesMixin
from .resources import ResourcesMixin
from .generics import GenericsMixin
from .closures import ClosuresMixin
from .optionals import OptionalsMixin
from .conditionals import ConditionalsMixin
from .loops import LoopsMixin
from .methods import MethodsMixin
from .statements import StatementsMixin
from .operators import OperatorsMixin
from .calls import CallsMixin
from .collections import CollectionsMixin
from .structs import StructsMixin
from .match import MatchMixin
from .results import ResultsMixin
import copy


class CodeGenerator(ResultsMixin, MatchMixin, StructsMixin, CollectionsMixin, CallsMixin, OperatorsMixin, StatementsMixin, MethodsMixin, LoopsMixin, ConditionalsMixin, OptionalsMixin, ClosuresMixin, GenericsMixin, TypesMixin, ResourcesMixin):
    def __init__(self, namespace: Namespace):
        # Unified namespace from type checker (Phase 0 of module system)
        self.namespace = namespace

        # Initialize LLVM
        binding.initialize()
        binding.initialize_native_target()
        binding.initialize_native_asmprinter()

        # Create module
        self.module = ir.Module(name="saw_module")
        self.module.triple = binding.get_default_triple()

        # Create target data for sizeof calculations
        target = binding.Target.from_triple(binding.get_default_triple())
        target_machine = target.create_target_machine()
        self.target_data = binding.create_target_data(str(target_machine.target_data))

        # Builder will be set when generating function bodies
        self.builder: ir.IRBuilder = None

        # Symbol table for variables (name -> alloca instruction)
        self.variables: dict = {}

        # Function table
        self.functions: dict = {}

        # Struct types (name -> (LLVM type, field_order))
        self.struct_types: dict = {}

        # Enum types (name -> (LLVM type, variant_tags, variant_info))
        # variant_tags: dict[variant_name, tag_value]
        # variant_info: dict[variant_name, list[(param_name, SawType)]]
        self.enum_types: dict = {}

        # String constants
        self.string_constants: dict = {}
        self.string_counter = 0

        # Loop tracking for break/continue
        # Stack of (continue_block, break_block, result_storage) for nested loops
        # result_storage is None for statement context, alloca for expression context
        self.loop_stack: List[tuple] = []

        # Generics support
        # Maps type parameter names to concrete SawTypes during instantiation
        self.type_param_context: dict[str, SawType] = {}
        # Stores original AST of generic functions for later instantiation
        self.generic_functions: dict[str, Function] = {}
        # Stores original AST of generic structs for later instantiation
        self.generic_structs: dict[str, Struct] = {}
        # Stores original AST of generic enums for later instantiation
        self.generic_enums: dict[str, Enum] = {}

        # Self type context - the struct name when generating extension methods
        self.self_type_context: Optional[str] = None
        # Stores original AST of generic extensions for later instantiation
        # Multiple extensions can exist for the same struct (methods + conformances)
        self.generic_extensions: dict[str, List[Extension]] = {}
        # Stores specialized extensions keyed by (struct_name, type_args_tuple)
        # e.g., ("Vector", ("String",)) -> [Extension for Vector<String>]
        self.specialized_extensions: dict[tuple, List[Extension]] = {}
        # Tracks which monomorphized functions have been generated
        self.generated_instantiations: set[str] = set()
        # Queue for pending method body generation: (mangled_struct_name, method, type_mapping, is_init)
        # Bodies are generated after all signatures are declared
        self.pending_method_bodies: List[tuple] = []

        # Closure counter for unique names
        self.closure_counter = 0

        # Variable types for closure captures (name -> SawType)
        self.variable_types: dict[str, SawType] = {}

        # Default parameter values: mangled_name -> list of default Expression (or None)
        self.method_defaults: dict[str, list] = {}

        # Resource management: variable lifetime tracking
        # Stack of scopes, each scope is a list of (var_name, saw_type) for variables needing cleanup
        self.cleanup_stack: List[List[tuple[str, SawType]]] = []
        # Cache: type_name -> cleanup behavior ('none', 'deinit', 'custom_copy', 'no_copy')
        self.type_cleanup_behavior: dict[str, str] = {}
        # Track moved variables - these should not be cleaned up or accessed
        self.moved_variables: set[str] = set()

        # Extern functions that return optionals (need NULL check at call site)
        # Maps function name -> inner SawType (unwrapped from optional)
        self.extern_optional_returns: dict[str, SawType] = {}

        # Current return type (for implicit optional wrapping)
        self.current_return_type: Optional[SawType] = None

        # Declare external functions (printf for print)
        self._declare_external_functions()

    # Built-in type names for detecting specialized extensions
    BUILTIN_TYPE_NAMES = {
        'Int', 'UInt', 'Float', 'Bool', 'String',
        'Int8', 'Int16', 'Int32', 'Int64',
        'UInt8', 'UInt16', 'UInt32', 'UInt64',
    }

    def _get_extension_specialization(self, extension: Extension) -> tuple:
        """Get the specialization key for an extension, or empty tuple if generic.

        Returns tuple of type arg names if specialized (e.g., ("String",)),
        or empty tuple if it's a generic extension.
        """
        if not extension.type_params:
            return ()

        # Check if all type params are known types (specialization)
        type_args = []
        for tp in extension.type_params:
            if tp.name in self.BUILTIN_TYPE_NAMES or tp.name in self.struct_types:
                type_args.append(tp.name)
            else:
                # Not a known type, this is a generic extension
                return ()

        return tuple(type_args)

    def _declare_external_functions(self):
        # Declare printf
        printf_type = ir.FunctionType(
            ir.IntType(32),
            [ir.PointerType(ir.IntType(8))],
            var_arg=True
        )
        self.printf = ir.Function(self.module, printf_type, name="printf")

        # Declare abort for runtime panics
        abort_type = ir.FunctionType(ir.VoidType(), [])
        self.abort = ir.Function(self.module, abort_type, name="abort")

        # Declare snprintf for string formatting
        snprintf_type = ir.FunctionType(
            ir.IntType(32),
            [ir.PointerType(ir.IntType(8)), ir.IntType(64), ir.PointerType(ir.IntType(8))],
            var_arg=True
        )
        self.snprintf = ir.Function(self.module, snprintf_type, name="snprintf")

        # Declare strcpy for string copying
        strcpy_type = ir.FunctionType(
            ir.PointerType(ir.IntType(8)),
            [ir.PointerType(ir.IntType(8)), ir.PointerType(ir.IntType(8))]
        )
        self.strcpy = ir.Function(self.module, strcpy_type, name="strcpy")

        # Declare strcat for string concatenation
        strcat_type = ir.FunctionType(
            ir.PointerType(ir.IntType(8)),
            [ir.PointerType(ir.IntType(8)), ir.PointerType(ir.IntType(8))]
        )
        self.strcat = ir.Function(self.module, strcat_type, name="strcat")

    # _get_llvm_type is now in codegen_types.py (TypesMixin)

    # Resource management methods are now in codegen_resources.py (ResourcesMixin)

    def _create_string_constant(self, value: str) -> ir.GlobalVariable:
        if value in self.string_constants:
            return self.string_constants[value]

        # Add null terminator
        encoded = (value + '\0').encode('utf-8')
        str_type = ir.ArrayType(ir.IntType(8), len(encoded))

        name = f".str.{self.string_counter}"
        self.string_counter += 1

        global_str = ir.GlobalVariable(self.module, str_type, name=name)
        global_str.linkage = 'private'
        global_str.global_constant = True
        global_str.initializer = ir.Constant(str_type, bytearray(encoded))

        self.string_constants[value] = global_str
        return global_str

    def generate(self, program: Program) -> str:
        # Type aliases are already in namespace from typechecker

        # Register built-in generic enums (like Result<T, E>)
        self._register_builtin_enums()

        # First pass: register struct types
        for struct in program.structs:
            self._register_struct(struct)

        # Third pass: register enum types
        for enum in program.enums:
            self._register_enum(enum)

        # Interfaces, type conformances, and type assignments are in namespace from typechecker

        # Declare extern functions (FFI)
        for extern_block in program.extern_blocks:
            for extern_func in extern_block.functions:
                self._declare_extern_function(extern_func)

        # Fourth pass: declare all functions (skip generic functions)
        for func in program.functions:
            if func.type_params:
                # Store generic function for later instantiation
                self.generic_functions[func.name] = func
            else:
                self._declare_function(func)

        # First pass: store generic and specialized extensions separately
        for extension in program.extensions:
            if extension.type_params:
                spec_key = self._get_extension_specialization(extension)
                if spec_key:
                    # Specialized extension (e.g., extension Vector<String>)
                    full_key = (extension.struct_name, spec_key)
                    if full_key not in self.specialized_extensions:
                        self.specialized_extensions[full_key] = []
                    self.specialized_extensions[full_key].append(extension)
                else:
                    # Generic extension (e.g., extension Vector<T>)
                    if extension.struct_name not in self.generic_extensions:
                        self.generic_extensions[extension.struct_name] = []
                    self.generic_extensions[extension.struct_name].append(extension)

        # Second pass: declare non-generic extension methods
        for extension in program.extensions:
            if not extension.type_params:
                self._declare_extension_methods(extension)

        # Fifth pass: generate function bodies (skip generic functions)
        for func in program.functions:
            if not func.type_params:
                self._generate_function(func)

        # Generate extension method bodies
        for extension in program.extensions:
            self._generate_extension_methods(extension)

        # Generate pending monomorphized method bodies
        # These were queued during monomorphization to ensure all signatures exist first
        self._generate_pending_method_bodies()

        return str(self.module)

    # _resolve_type_alias is now in codegen_types.py (TypesMixin)

    def _register_struct(self, struct: Struct):
        """Register a struct type with LLVM."""
        # Skip generic structs - they'll be monomorphized when used
        if struct.type_params:
            self.generic_structs[struct.name] = struct
            return

        # Get LLVM types for each field
        field_types = [self._get_llvm_type(field.type) for field in struct.fields]

        # Create identified struct type (unique identity even if same field types)
        llvm_struct_type = self.module.context.get_identified_type(struct.name)
        llvm_struct_type.set_body(*field_types)

        # Store the type and field order for later use
        field_order = [field.name for field in struct.fields]
        self.struct_types[struct.name] = (llvm_struct_type, field_order)
        # Struct field types are in namespace

    def _register_builtin_enums(self):
        """Register built-in generic enums like Result<T, E>.

        These are defined as builtins in the typechecker but need to be
        registered in codegen for monomorphization.
        """
        # Create a synthetic Enum AST node for Result<T, E>
        result_enum = Enum(
            name="Result",
            variants=[
                EnumVariant(
                    name="Ok",
                    associated_types=[("value", SawType(TypeKind.TYPE_PARAM, type_param_name="T"))]
                ),
                EnumVariant(
                    name="Err",
                    associated_types=[("error", SawType(TypeKind.TYPE_PARAM, type_param_name="E"))]
                )
            ],
            type_params=[
                TypeParameter(name="T", line=0, column=0),
                TypeParameter(name="E", line=0, column=0)
            ],
            line=0, column=0
        )
        self.generic_enums["Result"] = result_enum

    def _register_enum(self, enum: Enum):
        """Register an enum type with LLVM.
        Enums are represented as tagged unions: { i32 tag, [N x i8] payload }
        or just i32 if all variants have no associated values."""
        # Skip generic enums - they'll be monomorphized when used
        if enum.type_params:
            self.generic_enums[enum.name] = enum
            return

        self._register_concrete_enum(enum.name, enum.variants)

    def _register_concrete_enum(self, name: str, variants: List[EnumVariant]):
        """Register a concrete (non-generic or monomorphized) enum type with LLVM."""
        # Assign tag values to variants (0, 1, 2, ...)
        variant_tags = {}
        variant_info = {}
        max_payload_size = 0

        for i, variant in enumerate(variants):
            variant_tags[variant.name] = i
            variant_info[variant.name] = variant.associated_types

            # Calculate payload size for this variant
            if variant.associated_types:
                variant_types = [self._get_llvm_type(typ) for _, typ in variant.associated_types]
                # Create a struct to hold the associated values
                if variant_types:
                    variant_struct = ir.LiteralStructType(variant_types)
                    # Get size of the variant struct in bytes
                    # For simplicity, we calculate a conservative size
                    # In a real implementation, we'd use LLVM's DataLayout
                    size = sum(self._estimate_type_size(t) for t in variant_types)
                    max_payload_size = max(max_payload_size, size)

        # Create LLVM type for enum
        if max_payload_size > 0:
            # Enum with associated values: { i32 tag, [N x i8] payload }
            llvm_enum_type = ir.LiteralStructType([
                ir.IntType(32),  # tag
                ir.ArrayType(ir.IntType(8), max_payload_size)  # payload
            ])
        else:
            # Simple enum (no associated values): just i32 tag
            llvm_enum_type = ir.IntType(32)

        # Store enum info
        self.enum_types[name] = (llvm_enum_type, variant_tags, variant_info)

    # _estimate_type_size is now in codegen_types.py (TypesMixin)

    def _declare_function(self, func: Function, name_override: str = None):
        """Declare a function. If name_override is provided, use it instead of func.name."""
        func_name = name_override if name_override else func.name
        param_types = [self._get_llvm_type(p.type) for p in func.parameters]
        return_type = self._get_llvm_type(func.return_type)

        # Main function should return int for proper exit code
        if func_name == "main" and func.return_type.kind == TypeKind.VOID:
            return_type = ir.IntType(32)

        func_type = ir.FunctionType(return_type, param_types)
        llvm_func = ir.Function(self.module, func_type, name=func_name)
        self.functions[func_name] = llvm_func
        # Function return types are now in namespace

    def _declare_extern_function(self, extern_func: ExternFunction):
        """Declare an external C function (no body, just LLVM declare)."""
        # Skip if already declared (can happen with std library and user code both declaring)
        if extern_func.name in self.functions:
            return

        param_types = [self._get_llvm_type(p.type) for p in extern_func.parameters]

        # For extern functions, unwrap optionals from return type for C ABI
        # C functions return raw pointers which can be NULL
        saw_return_type = extern_func.return_type
        if saw_return_type.kind == TypeKind.OPTIONAL and saw_return_type.inner_type:
            # Store that this extern returns optional (for wrapping at call site)
            self.extern_optional_returns[extern_func.name] = saw_return_type.inner_type
            return_type = self._get_llvm_type(saw_return_type.inner_type)
        else:
            return_type = self._get_llvm_type(saw_return_type)

        func_type = ir.FunctionType(return_type, param_types, var_arg=extern_func.is_variadic)
        llvm_func = ir.Function(self.module, func_type, name=extern_func.name)
        # Set external linkage (default for declarations)
        llvm_func.linkage = 'external'
        self.functions[extern_func.name] = llvm_func

    # Generic methods moved to codegen_generics.py (GenericsMixin)

    def _declare_extension_methods(self, extension: Extension):
        """Declare all methods in an extension."""
        # Generic extensions are already stored and will be monomorphized when used
        if extension.type_params:
            return

        # Set Self type context for this extension
        old_self_context = self.self_type_context
        self.self_type_context = extension.struct_name

        for method in extension.methods:
            # Create mangled name
            if method.is_init:
                # Include parameter names for init methods to allow overloading
                param_names = [p.name for p in method.parameters]
                mangled_name = self._mangle_method_name(extension.struct_name, method.name, param_names)
            else:
                mangled_name = self._mangle_method_name(extension.struct_name, method.name)

            # Build parameter types
            if method.is_init:
                # Init methods take parameters (no self) and return the struct
                # Primitive type extensions (String) don't support init methods
                if extension.struct_name == "String":
                    raise ValueError("Cannot define init methods on String")
                param_types = [self._get_llvm_type(p.type) for p in method.parameters]
                # Return type is the struct being initialized
                struct_type, _ = self.struct_types[extension.struct_name]
                return_type = struct_type
            elif method.is_static:
                # Static methods have no self parameter
                param_types = [self._get_llvm_type(p.type) for p in method.parameters]
                return_type = self._get_llvm_type(method.return_type)
            else:
                # Regular instance methods include self as first parameter
                # Determine the Self type for this extension
                if extension.struct_name == "String":
                    self_llvm_type = ir.IntType(8).as_pointer()  # String is i8*
                else:
                    self_llvm_type = self.struct_types[extension.struct_name][0]

                param_types = []
                for i, p in enumerate(method.parameters):
                    # Handle 'self' parameter specially - its type is VOID placeholder
                    if p.name == "self":
                        llvm_type = self_llvm_type
                    else:
                        llvm_type = self._get_llvm_type(p.type)
                    # If first param is self and it's mutable, make it a pointer
                    if i == 0 and p.name == "self" and method.self_mutable:
                        llvm_type = llvm_type.as_pointer()
                    param_types.append(llvm_type)
                return_type = self._get_llvm_type(method.return_type)

            # Create function type
            func_type = ir.FunctionType(return_type, param_types)
            llvm_func = ir.Function(self.module, func_type, name=mangled_name)

            # Store in functions table
            self.functions[mangled_name] = llvm_func
            # Method return types and static method info are in namespace

            # Track default parameter values
            defaults = [p.default_value for p in method.parameters]
            if any(d is not None for d in defaults):
                self.method_defaults[mangled_name] = defaults

        # Restore Self type context
        self.self_type_context = old_self_context

    # Method/function generation moved to codegen_methods.py (MethodsMixin)
    # Statement generation moved to codegen_statements.py (StatementsMixin)

    def _generate_expression(self, expr: Expression, need_result: bool = True):
        """Generate code for an expression.

        Args:
            expr: The expression to generate code for
            need_result: If False, we don't need the expression's value (statement context).
                        This allows skipping result-capturing logic in if/if-let.
        """
        # Store the flag so nested calls can access it
        old_need_result = getattr(self, '_need_result', True)
        self._need_result = need_result

        method_name = f'visit_{expr.__class__.__name__}'
        visitor = getattr(self, method_name, None)
        if visitor is None:
            raise ValueError(f"Unknown expression type: {type(expr)}")
        result = visitor(expr)

        self._need_result = old_need_result
        return result

    # ===== Expression Visitor Methods =====

    def visit_IntLiteral(self, expr: IntLiteral):
        return ir.Constant(ir.IntType(64), expr.value)

    def visit_FloatLiteral(self, expr: FloatLiteral):
        return ir.Constant(ir.DoubleType(), expr.value)

    def visit_BoolLiteral(self, expr: BoolLiteral):
        return ir.Constant(ir.IntType(1), 1 if expr.value else 0)

    def visit_StringLiteral(self, expr: StringLiteral):
        global_str = self._create_string_constant(expr.value)
        zero = ir.Constant(ir.IntType(32), 0)
        return self.builder.gep(global_str, [zero, zero], inbounds=True)

    def visit_StringInterpolation(self, expr: StringInterpolation):
        """Generate code for string interpolation: "Hello {name}!"

        Strategy: Allocate a buffer, copy/concatenate parts and converted expressions.
        """
        zero = ir.Constant(ir.IntType(32), 0)

        # Allocate a buffer for the result (1024 bytes should be enough for most cases)
        buf_size = 1024
        buf = self.builder.alloca(ir.ArrayType(ir.IntType(8), buf_size), name="interp_buf")
        buf_ptr = self.builder.gep(buf, [zero, zero], inbounds=True)

        # Initialize buffer with first part
        if expr.parts[0]:
            first = self._create_string_constant(expr.parts[0])
            first_ptr = self.builder.gep(first, [zero, zero], inbounds=True)
            self.builder.call(self.strcpy, [buf_ptr, first_ptr])
        else:
            # Empty first part - set null terminator
            self.builder.store(ir.Constant(ir.IntType(8), 0), buf_ptr)

        # Append each expression and following part
        for i, sub_expr in enumerate(expr.expressions):
            # Get expression value and convert to string
            value = self._generate_expression(sub_expr)
            saw_type = self._infer_saw_type(sub_expr)
            str_ptr = self._value_to_string(value, saw_type)

            # Append expression string
            self.builder.call(self.strcat, [buf_ptr, str_ptr])

            # Append following string part (if non-empty)
            if expr.parts[i + 1]:
                part = self._create_string_constant(expr.parts[i + 1])
                part_ptr = self.builder.gep(part, [zero, zero], inbounds=True)
                self.builder.call(self.strcat, [buf_ptr, part_ptr])

        return buf_ptr

    def _value_to_string(self, value, saw_type: SawType):
        """Convert an LLVM value to a string pointer using snprintf."""
        zero = ir.Constant(ir.IntType(32), 0)

        if saw_type is None:
            # Fallback for unknown types
            fallback = self._create_string_constant("<?>")
            return self.builder.gep(fallback, [zero, zero], inbounds=True)

        if saw_type.kind == TypeKind.STRING:
            return value  # Already a string

        # Allocate buffer for number-to-string conversion (64 bytes is enough)
        buf_size = 64
        buf = self.builder.alloca(ir.ArrayType(ir.IntType(8), buf_size), name="fmt_buf")
        buf_ptr = self.builder.gep(buf, [zero, zero], inbounds=True)
        size = ir.Constant(ir.IntType(64), buf_size)

        if saw_type.kind == TypeKind.BOOL:
            # Bool: use select for "true"/"false"
            true_str = self._create_string_constant("true")
            false_str = self._create_string_constant("false")
            true_ptr = self.builder.gep(true_str, [zero, zero], inbounds=True)
            false_ptr = self.builder.gep(false_str, [zero, zero], inbounds=True)
            return self.builder.select(value, true_ptr, false_ptr)

        elif saw_type.kind in {TypeKind.INT, TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64}:
            fmt = self._create_string_constant("%lld")
            fmt_ptr = self.builder.gep(fmt, [zero, zero], inbounds=True)
            # Extend to i64 if needed
            if value.type.width < 64:
                value = self.builder.sext(value, ir.IntType(64), name="sext_fmt")
            self.builder.call(self.snprintf, [buf_ptr, size, fmt_ptr, value])
            return buf_ptr

        elif saw_type.kind in {TypeKind.UINT, TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64}:
            fmt = self._create_string_constant("%llu")
            fmt_ptr = self.builder.gep(fmt, [zero, zero], inbounds=True)
            # Extend to i64 if needed
            if value.type.width < 64:
                value = self.builder.zext(value, ir.IntType(64), name="zext_fmt")
            self.builder.call(self.snprintf, [buf_ptr, size, fmt_ptr, value])
            return buf_ptr

        elif saw_type.kind == TypeKind.FLOAT:
            fmt = self._create_string_constant("%g")
            fmt_ptr = self.builder.gep(fmt, [zero, zero], inbounds=True)
            self.builder.call(self.snprintf, [buf_ptr, size, fmt_ptr, value])
            return buf_ptr

        else:
            # Fallback for unknown types
            fallback = self._create_string_constant("<?>")
            return self.builder.gep(fallback, [zero, zero], inbounds=True)

    def visit_Identifier(self, expr: Identifier):
        if expr.name not in self.variables:
            raise ValueError(f"Undefined variable: {expr.name}")
        return self.builder.load(self.variables[expr.name], name=expr.name)

    def visit_BinaryOp(self, expr: BinaryOp):
        return self._generate_binary_op(expr)

    def visit_UnaryOp(self, expr: UnaryOp):
        return self._generate_unary_op(expr)

    def visit_MoveExpr(self, expr: MoveExpr):
        return self._generate_move_expr(expr)

    def visit_CastExpr(self, expr: CastExpr):
        return self._generate_cast_expr(expr)

    def visit_FunctionCall(self, expr: FunctionCall):
        return self._generate_function_call(expr)

    def visit_IfExpr(self, expr: IfExpr):
        return self._generate_if_expression(expr)

    def visit_IfLetExpr(self, expr: IfLetExpr):
        return self._generate_if_let_expression(expr)

    def visit_TupleLiteral(self, expr: TupleLiteral):
        return self._generate_tuple_literal(expr)

    def visit_TupleIndex(self, expr: TupleIndex):
        return self._generate_tuple_index(expr)

    def visit_ArrayLiteral(self, expr: ArrayLiteral):
        return self._generate_array_literal(expr)

    def visit_ArrayIndex(self, expr: ArrayIndex):
        return self._generate_array_index(expr)

    def visit_MemberAccess(self, expr: MemberAccess):
        return self._generate_member_access(expr)

    def visit_StructInit(self, expr: StructInit):
        return self._generate_struct_init(expr)

    def visit_NoneLiteral(self, expr: NoneLiteral):
        return self._generate_none_literal(expr)

    def visit_ForceUnwrap(self, expr: ForceUnwrap):
        return self._generate_force_unwrap(expr)

    def visit_NilCoalesce(self, expr: NilCoalesce):
        return self._generate_nil_coalesce(expr)

    def visit_OptionalChain(self, expr: OptionalChain):
        return self._generate_optional_chain(expr)

    def visit_TryExpr(self, expr: TryExpr):
        return self._generate_try_expr(expr)

    def visit_TryCatchExpr(self, expr: TryCatchExpr):
        return self._generate_try_catch_expr(expr)

    def visit_MethodCall(self, expr: MethodCall):
        return self._generate_method_call(expr)

    def visit_SelfExpr(self, expr: SelfExpr):
        return self._generate_self_expr(expr)

    def visit_EnumInit(self, expr: EnumInit):
        return self._generate_enum_init(expr)

    def visit_MatchExpr(self, expr: MatchExpr):
        return self._generate_match_expr(expr)

    def visit_WhileExpr(self, expr: WhileExpr):
        return self._generate_while_expr_value(expr)

    def visit_ForLoop(self, expr: ForLoop):
        return self._generate_for_loop_value(expr)

    def visit_ClosureExpr(self, expr: ClosureExpr):
        return self._generate_closure(expr)

    # Operator methods moved to codegen_operators.py (OperatorsMixin)

    # Function call methods moved to codegen_calls.py (CallsMixin)
    # Conditional methods moved to codegen_conditionals.py (ConditionalsMixin)
    # Collection methods moved to codegen_collections.py (CollectionsMixin)
    # Struct methods moved to codegen_structs.py (StructsMixin)
    # Optional methods moved to codegen_optionals.py (OptionalsMixin)
    # Method call methods moved to codegen_calls.py (CallsMixin)
    # Enum init moved to codegen_calls.py (CallsMixin)
    # Match expression moved to codegen_match.py (MatchMixin)
    # Closure methods moved to codegen_closures.py (ClosuresMixin)

    def compile_to_object(self, output_path: str):
        """Compile the module to an object file."""
        llvm_ir = str(self.module)

        # Parse the IR
        mod = binding.parse_assembly(llvm_ir)
        mod.verify()

        # Create target machine
        target = binding.Target.from_default_triple()
        target_machine = target.create_target_machine()

        # Emit object code
        with open(output_path, 'wb') as f:
            f.write(target_machine.emit_object(mod))

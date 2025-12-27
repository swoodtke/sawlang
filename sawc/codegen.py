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
    GuardLetStatement,
    Struct, StructField,
    Enum, EnumVariant, EnumInit, MatchExpr, MatchArm,
    Extension, Method, MethodCall, SelfExpr,
    SawType, TypeKind, Argument, TypeParameter, TypeDefinition,
    ExternFunction, ExternBlock,
    ClosureExpr
)
from namespace import Namespace
import copy


class CodeGenerator:
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
        # Tracks which monomorphized functions have been generated
        self.generated_instantiations: set[str] = set()

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

    def _get_llvm_type(self, saw_type: SawType) -> ir.Type:
        if saw_type.kind == TypeKind.INT:
            return ir.IntType(64)
        elif saw_type.kind == TypeKind.FLOAT:
            return ir.DoubleType()
        elif saw_type.kind == TypeKind.BOOL:
            return ir.IntType(1)
        elif saw_type.kind == TypeKind.STRING:
            return ir.PointerType(ir.IntType(8))
        # Fixed-width integers
        elif saw_type.kind == TypeKind.INT8:
            return ir.IntType(8)
        elif saw_type.kind == TypeKind.INT16:
            return ir.IntType(16)
        elif saw_type.kind == TypeKind.INT32:
            return ir.IntType(32)
        elif saw_type.kind == TypeKind.INT64:
            return ir.IntType(64)
        elif saw_type.kind == TypeKind.UINT8:
            return ir.IntType(8)
        elif saw_type.kind == TypeKind.UINT16:
            return ir.IntType(16)
        elif saw_type.kind == TypeKind.UINT32:
            return ir.IntType(32)
        elif saw_type.kind == TypeKind.UINT64:
            return ir.IntType(64)
        elif saw_type.kind == TypeKind.POINTER:
            # Raw pointer type: UnsafePointer<T> or UnsafeConstPointer<T>
            if saw_type.inner_type is None:
                raise ValueError("Pointer type missing inner type")
            pointee_type = self._get_llvm_type(saw_type.inner_type)
            return ir.PointerType(pointee_type)
        elif saw_type.kind == TypeKind.VOID:
            return ir.VoidType()
        elif saw_type.kind == TypeKind.TUPLE:
            # Tuples are represented as LLVM structs
            if saw_type.element_types is None:
                return ir.LiteralStructType([])
            element_llvm_types = [self._get_llvm_type(t) for t in saw_type.element_types]
            return ir.LiteralStructType(element_llvm_types)
        elif saw_type.kind == TypeKind.STRUCT:
            # Look up the struct type (might actually be an enum, type param, or type alias)
            if saw_type.struct_name is None:
                raise ValueError("Struct type missing name")
            # Check if it's a type alias (use namespace)
            alias_sym = self.namespace.lookup_type_alias(saw_type.struct_name)
            if alias_sym and alias_sym.aliased_type:
                return self._get_llvm_type(alias_sym.aliased_type)
            # Check if it's a type parameter in the current context
            if saw_type.struct_name in self.type_param_context:
                return self._get_llvm_type(self.type_param_context[saw_type.struct_name])
            # Check if it's actually an enum
            if saw_type.struct_name in self.enum_types:
                return self.enum_types[saw_type.struct_name][0]  # Return LLVM type
            # Handle generic struct with type arguments (e.g., VectorIterator<Int>)
            if saw_type.type_args:
                mangled_name = self._ensure_monomorphized_struct(saw_type.struct_name, saw_type.type_args)
                return self.struct_types[mangled_name][0]
            if saw_type.struct_name not in self.struct_types:
                raise ValueError(f"Undefined struct: {saw_type.struct_name}")
            return self.struct_types[saw_type.struct_name][0]  # Return LLVM type
        elif saw_type.kind == TypeKind.OPTIONAL:
            # Optionals are represented as { i1, T } where i1 indicates presence
            if saw_type.inner_type is None:
                # None literal with unknown type - use i64 as placeholder
                inner_llvm_type = ir.IntType(64)
            else:
                inner_llvm_type = self._get_llvm_type(saw_type.inner_type)
            return ir.LiteralStructType([ir.IntType(1), inner_llvm_type])
        elif saw_type.kind == TypeKind.ENUM:
            # Look up the enum type
            if saw_type.enum_name is None:
                raise ValueError("Enum type missing name")
            # Handle generic enum with type_args
            if saw_type.type_args:
                mangled_name = self._ensure_monomorphized_enum(saw_type.enum_name, saw_type.type_args)
                return self.enum_types[mangled_name][0]
            if saw_type.enum_name not in self.enum_types:
                raise ValueError(f"Undefined enum: {saw_type.enum_name}")
            return self.enum_types[saw_type.enum_name][0]  # Return LLVM type
        elif saw_type.kind == TypeKind.TYPE_PARAM:
            # Look up the type parameter in the current context
            if saw_type.type_param_name is None:
                raise ValueError("Type parameter missing name")
            if saw_type.type_param_name not in self.type_param_context:
                raise ValueError(f"Unbound type parameter: {saw_type.type_param_name}")
            return self._get_llvm_type(self.type_param_context[saw_type.type_param_name])
        elif saw_type.kind == TypeKind.ARRAY:
            # Arrays are LLVM array types [N x T]
            if saw_type.array_element_type is None or saw_type.array_size is None:
                raise ValueError("Array type missing element type or size")
            elem_type = self._get_llvm_type(saw_type.array_element_type)
            return ir.ArrayType(elem_type, saw_type.array_size)
        elif saw_type.kind == TypeKind.FUNCTION:
            # Closures are { fn_ptr, env_ptr } where fn_ptr takes (env_ptr, params...) -> ret
            param_types = [self._get_llvm_type(t) for t in (saw_type.param_types or [])]
            if saw_type.func_return_type and saw_type.func_return_type.kind != TypeKind.VOID:
                ret_type = self._get_llvm_type(saw_type.func_return_type)
            else:
                ret_type = ir.VoidType()
            # Function takes env_ptr (i8*) as first parameter
            env_ptr_type = ir.PointerType(ir.IntType(8))
            fn_type = ir.FunctionType(ret_type, [env_ptr_type] + param_types)
            fn_ptr_type = ir.PointerType(fn_type)
            # Closure struct: { fn_ptr, env_ptr }
            return ir.LiteralStructType([fn_ptr_type, env_ptr_type])
        elif saw_type.kind == TypeKind.SELF:
            # Self type - resolve to current struct context
            if self.self_type_context is None:
                raise ValueError("Self type used outside of extension context")
            # Special handling for primitive type extensions
            if self.self_type_context == "String":
                return ir.IntType(8).as_pointer()  # String is i8*
            if self.self_type_context not in self.struct_types:
                raise ValueError(f"Self type refers to undefined struct: {self.self_type_context}")
            return self.struct_types[self.self_type_context][0]
        else:
            raise ValueError(f"Unknown type: {saw_type}")

    # =========================================================================
    # Resource Management Helpers
    # =========================================================================

    def _get_type_name_for_conformance(self, saw_type: SawType) -> Optional[str]:
        """Get the type name for conformance lookup."""
        if saw_type.kind == TypeKind.STRUCT:
            if saw_type.type_args:
                # Generic instantiation: Box<Int> -> Box$Int
                args = "_".join(self._get_type_name_for_conformance(arg) or "unknown"
                               for arg in saw_type.type_args)
                return f"{saw_type.struct_name}${args}"
            return saw_type.struct_name
        elif saw_type.kind == TypeKind.ENUM:
            if saw_type.type_args:
                args = "_".join(self._get_type_name_for_conformance(arg) or "unknown"
                               for arg in saw_type.type_args)
                return f"{saw_type.enum_name}${args}"
            return saw_type.enum_name
        return None

    def _get_cleanup_behavior(self, saw_type: SawType) -> str:
        """Determine cleanup behavior for a type: 'none', 'deinit', 'custom_copy', 'no_copy'."""
        type_name = self._get_type_name_for_conformance(saw_type)
        if type_name is None:
            return "none"

        # Check cache
        if type_name in self.type_cleanup_behavior:
            return self.type_cleanup_behavior[type_name]

        # Check conformances (use namespace)
        conformances = self.namespace.get_conformances(type_name)

        if "NoCopy" in conformances:
            behavior = "no_copy"
        elif "CustomCopy" in conformances:
            behavior = "custom_copy"
        elif "Deinit" in conformances:
            behavior = "deinit"
        else:
            behavior = "none"

        self.type_cleanup_behavior[type_name] = behavior
        return behavior

    def _needs_cleanup(self, saw_type: SawType) -> bool:
        """Check if a type needs cleanup (implements Deinit, CustomCopy, or NoCopy)."""
        return self._get_cleanup_behavior(saw_type) != "none"

    def _generate_deinit_call(self, var_name: str, saw_type: SawType):
        """Generate a call to deinit() for a variable."""
        type_name = self._get_type_name_for_conformance(saw_type)
        if type_name is None:
            return

        deinit_method_name = self._mangle_method_name(type_name, "deinit")

        if deinit_method_name not in self.functions:
            # No deinit method found - this shouldn't happen if type tracking is correct
            return

        deinit_fn = self.functions[deinit_method_name]
        var_ptr = self.variables.get(var_name)
        if var_ptr is None:
            return

        # deinit takes var self (pointer)
        self.builder.call(deinit_fn, [var_ptr])

    def _generate_copy(self, value, saw_type: SawType):
        """Generate a copy of a value, calling copy() for CustomCopy types.

        Returns the copied value (which may be the original for non-CustomCopy types).
        """
        behavior = self._get_cleanup_behavior(saw_type)

        if behavior == "no_copy":
            # NoCopy types cannot be copied - this should be caught by typechecker
            raise ValueError(f"Cannot copy NoCopy type: {saw_type}")

        if behavior != "custom_copy":
            # Regular types just use the value as-is (bitwise copy)
            return value

        # CustomCopy: call the copy() method
        type_name = self._get_type_name_for_conformance(saw_type)
        if type_name is None:
            return value

        copy_method_name = self._mangle_method_name(type_name, "copy")

        if copy_method_name not in self.functions:
            # No copy method found - fall back to bitwise copy
            return value

        copy_fn = self.functions[copy_method_name]

        # copy(self) takes self by value (immutable), returns Self
        return self.builder.call(copy_fn, [value], name="copy_result")

    def _needs_copy_for_struct_init(self, value_expr, field_type: SawType) -> bool:
        """Check if a value expression needs copy() called during struct initialization.

        We need to call copy() when:
        1. The field type implements CustomCopy
        2. The value comes from an existing variable (Identifier) or field access (MemberAccess)

        We don't need copy() for:
        - Fresh struct/enum construction (new values don't need copying)
        - Literals (they don't have existing ownership)
        - Move expressions (ownership is transferred)
        """
        # Check if the field type implements CustomCopy
        behavior = self._get_cleanup_behavior(field_type)
        if behavior != "custom_copy":
            return False

        # Check if the value comes from an existing binding that needs copying
        # Note: ast_nodes classes are already imported at module level

        if isinstance(value_expr, MoveExpr):
            # Move expressions transfer ownership, no copy needed
            return False

        if isinstance(value_expr, Identifier):
            # Identifier refers to an existing variable - needs copy
            return True

        if isinstance(value_expr, MemberAccess):
            # Member access (e.g., self.field) - needs copy
            return True

        # Fresh construction (struct init, enum init, literals) doesn't need copy
        return False

    def _cleanup_scope(self, scope_vars: List[tuple[str, SawType]]):
        """Generate cleanup code for all variables in a scope (in reverse declaration order)."""
        for var_name, saw_type in reversed(scope_vars):
            # Skip moved variables - ownership has been transferred
            if var_name in self.moved_variables:
                continue
            if var_name in self.variables:
                self._generate_deinit_call(var_name, saw_type)

    def _cleanup_all_scopes(self):
        """Generate cleanup code for all scopes (for early return)."""
        for scope_vars in reversed(self.cleanup_stack):
            self._cleanup_scope(scope_vars)

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

        # First pass: store generic extensions (needed for monomorphization)
        for extension in program.extensions:
            if extension.type_params:
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

        return str(self.module)

    def _resolve_type_alias(self, saw_type: SawType) -> SawType:
        """Resolve type aliases in a SawType."""
        if saw_type.kind == TypeKind.STRUCT and saw_type.struct_name:
            # Use namespace for type alias lookup
            alias_sym = self.namespace.lookup_type_alias(saw_type.struct_name)
            if alias_sym and alias_sym.aliased_type:
                return alias_sym.aliased_type
            if saw_type.type_args:
                resolved_args = [self._resolve_type_alias(t) for t in saw_type.type_args]
                return SawType(TypeKind.STRUCT, struct_name=saw_type.struct_name, type_args=resolved_args)
        elif saw_type.kind == TypeKind.OPTIONAL and saw_type.inner_type:
            resolved_inner = self._resolve_type_alias(saw_type.inner_type)
            return SawType(TypeKind.OPTIONAL, inner_type=resolved_inner)
        elif saw_type.kind == TypeKind.TUPLE and saw_type.element_types:
            resolved_elems = [self._resolve_type_alias(t) for t in saw_type.element_types]
            return SawType(TypeKind.TUPLE, element_types=resolved_elems)
        elif saw_type.kind == TypeKind.ENUM and saw_type.type_args:
            resolved_args = [self._resolve_type_alias(t) for t in saw_type.type_args]
            return SawType(TypeKind.ENUM, enum_name=saw_type.enum_name, type_args=resolved_args)
        return saw_type

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

    def _estimate_type_size(self, llvm_type: ir.Type) -> int:
        """Estimate the size of an LLVM type in bytes (conservative estimate)."""
        if isinstance(llvm_type, ir.IntType):
            return (llvm_type.width + 7) // 8  # Round up to nearest byte
        elif isinstance(llvm_type, ir.DoubleType):
            return 8
        elif isinstance(llvm_type, ir.FloatType):
            return 4
        elif isinstance(llvm_type, ir.PointerType):
            return 8  # Assume 64-bit pointers
        elif isinstance(llvm_type, (ir.LiteralStructType, ir.IdentifiedStructType)):
            # Sum of element sizes
            return sum(self._estimate_type_size(elem) for elem in llvm_type.elements)
        elif isinstance(llvm_type, ir.ArrayType):
            return llvm_type.count * self._estimate_type_size(llvm_type.element)
        else:
            return 8  # Default conservative estimate

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

    def _mangle_generic_name(self, func_name: str, type_args: List[SawType]) -> str:
        """Generate mangled name for generic instantiation: identity$Int or swap$Int_String"""
        type_names = []
        for t in type_args:
            type_names.append(self._type_to_string(t))
        return f"{func_name}${'_'.join(type_names)}"

    def _type_to_string(self, saw_type: SawType) -> str:
        """Convert a SawType to a string representation for name mangling."""
        if saw_type.kind == TypeKind.INT:
            return "Int"
        elif saw_type.kind == TypeKind.INT8:
            return "Int8"
        elif saw_type.kind == TypeKind.INT16:
            return "Int16"
        elif saw_type.kind == TypeKind.INT32:
            return "Int32"
        elif saw_type.kind == TypeKind.INT64:
            return "Int64"
        elif saw_type.kind == TypeKind.UINT8:
            return "UInt8"
        elif saw_type.kind == TypeKind.UINT16:
            return "UInt16"
        elif saw_type.kind == TypeKind.UINT32:
            return "UInt32"
        elif saw_type.kind == TypeKind.UINT64:
            return "UInt64"
        elif saw_type.kind == TypeKind.FLOAT:
            return "Float"
        elif saw_type.kind == TypeKind.BOOL:
            return "Bool"
        elif saw_type.kind == TypeKind.STRING:
            return "String"
        elif saw_type.kind == TypeKind.VOID:
            return "Void"
        elif saw_type.kind == TypeKind.POINTER:
            if saw_type.inner_type:
                return f"Ptr_{self._type_to_string(saw_type.inner_type)}"
            return "Ptr"
        elif saw_type.kind == TypeKind.TUPLE:
            if saw_type.element_types:
                inner = "_".join(self._type_to_string(t) for t in saw_type.element_types)
                return f"Tuple_{inner}"
            return "Tuple"
        elif saw_type.kind == TypeKind.STRUCT:
            return saw_type.struct_name
        elif saw_type.kind == TypeKind.OPTIONAL:
            if saw_type.inner_type:
                return f"Opt_{self._type_to_string(saw_type.inner_type)}"
            return "Opt"
        elif saw_type.kind == TypeKind.ENUM:
            return saw_type.enum_name
        else:
            return "Unknown"

    def _instantiate_generic_function(self, func_name: str, type_args: List[SawType]) -> str:
        """Instantiate a generic function with concrete type arguments.

        Returns the mangled name of the instantiated function.
        """
        if func_name not in self.generic_functions:
            raise ValueError(f"Unknown generic function: {func_name}")

        mangled_name = self._mangle_generic_name(func_name, type_args)

        # Check if already instantiated
        if mangled_name in self.generated_instantiations:
            return mangled_name

        # Get the generic function template
        generic_func = self.generic_functions[func_name]

        # Set up type parameter context
        if len(type_args) != len(generic_func.type_params):
            raise ValueError(
                f"Generic function {func_name} expects {len(generic_func.type_params)} "
                f"type arguments, got {len(type_args)}"
            )

        # Save current state (we might be in the middle of generating another function)
        saved_builder = self.builder
        saved_variables = self.variables.copy()
        saved_variable_types = self.variable_types.copy()
        saved_cleanup_stack = self.cleanup_stack[:]
        old_context = self.type_param_context.copy()

        # Build type parameter mapping
        for type_param, type_arg in zip(generic_func.type_params, type_args):
            self.type_param_context[type_param.name] = type_arg

            # Add associated type mappings for interface bounds
            for bound in type_param.bounds:
                # Get the concrete type name
                concrete_type_name = None
                if type_arg.kind == TypeKind.STRUCT:
                    concrete_type_name = type_arg.struct_name
                elif type_arg.kind == TypeKind.ENUM:
                    concrete_type_name = type_arg.enum_name

                if concrete_type_name:
                    # Get the associated type assignments for this (type, interface) pair (use namespace)
                    if concrete_type_name in self.namespace.conformances:
                        type_assigns = self.namespace.conformances[concrete_type_name].get(bound, {})
                        for assoc_name, assoc_type in type_assigns.items():
                            self.type_param_context[assoc_name] = assoc_type

        try:
            # Declare the instantiated function
            self._declare_function(generic_func, name_override=mangled_name)

            # Generate the function body
            self._generate_function(generic_func, name_override=mangled_name)

            # Mark as generated
            self.generated_instantiations.add(mangled_name)
        finally:
            # Restore state
            self.type_param_context = old_context
            self.builder = saved_builder
            self.variables = saved_variables
            self.variable_types = saved_variable_types
            self.cleanup_stack = saved_cleanup_stack

        return mangled_name

    def _mangle_method_name(self, struct_name: str, method_name: str, param_names: Optional[List[str]] = None) -> str:
        """Generate mangled name for methods: StructName_methodName
           For init methods, include parameter names to allow overloading."""
        if param_names is not None:
            # Init method - include parameter signature
            param_sig = '_'.join(param_names)
            return f"{struct_name}_{method_name}_{param_sig}"
        else:
            return f"{struct_name}_{method_name}"

    def _mangle_generic_struct_name(self, base_name: str, type_args: List[SawType]) -> str:
        """Generate mangled name for generic struct instantiation: Box<Int> -> Box_Int"""
        def type_to_string(t: SawType) -> str:
            if t.kind == TypeKind.INT:
                return "Int"
            elif t.kind == TypeKind.FLOAT:
                return "Float"
            elif t.kind == TypeKind.BOOL:
                return "Bool"
            elif t.kind == TypeKind.STRING:
                return "String"
            elif t.kind == TypeKind.STRUCT:
                if t.type_args:
                    return self._mangle_generic_struct_name(t.struct_name, t.type_args)
                return t.struct_name
            elif t.kind == TypeKind.ENUM:
                if t.type_args:
                    return self._mangle_generic_struct_name(t.enum_name, t.type_args)
                return t.enum_name
            elif t.kind == TypeKind.OPTIONAL:
                return f"Optional_{type_to_string(t.inner_type)}"
            elif t.kind == TypeKind.TUPLE:
                inner = "_".join(type_to_string(elem) for elem in t.element_types)
                return f"Tuple_{inner}"
            else:
                return str(t.kind.name)

        args_str = "_".join(type_to_string(t) for t in type_args)
        return f"{base_name}_{args_str}"

    def _substitute_saw_type(self, saw_type: SawType, type_mapping: dict[str, SawType]) -> SawType:
        """Substitute type parameters with concrete types in a SawType."""
        if saw_type.kind == TypeKind.TYPE_PARAM:
            if saw_type.type_param_name in type_mapping:
                return type_mapping[saw_type.type_param_name]
            return saw_type
        elif saw_type.kind == TypeKind.OPTIONAL:
            if saw_type.inner_type:
                new_inner = self._substitute_saw_type(saw_type.inner_type, type_mapping)
                return SawType(TypeKind.OPTIONAL, inner_type=new_inner)
            return saw_type
        elif saw_type.kind == TypeKind.POINTER:
            if saw_type.inner_type:
                new_inner = self._substitute_saw_type(saw_type.inner_type, type_mapping)
                return SawType(TypeKind.POINTER, inner_type=new_inner, pointer_mutable=saw_type.pointer_mutable)
            return saw_type
        elif saw_type.kind == TypeKind.TUPLE:
            if saw_type.element_types:
                new_elements = [self._substitute_saw_type(e, type_mapping) for e in saw_type.element_types]
                return SawType(TypeKind.TUPLE, element_types=new_elements)
            return saw_type
        elif saw_type.kind == TypeKind.STRUCT:
            # Check if this is actually a type parameter (parsed as STRUCT)
            if saw_type.struct_name in type_mapping:
                return type_mapping[saw_type.struct_name]
            if saw_type.type_args:
                new_type_args = [self._substitute_saw_type(t, type_mapping) for t in saw_type.type_args]
                return SawType(TypeKind.STRUCT, struct_name=saw_type.struct_name, type_args=new_type_args)
            return saw_type
        elif saw_type.kind == TypeKind.ENUM:
            if saw_type.type_args:
                new_type_args = [self._substitute_saw_type(t, type_mapping) for t in saw_type.type_args]
                return SawType(TypeKind.ENUM, enum_name=saw_type.enum_name, type_args=new_type_args)
            return saw_type
        else:
            return saw_type

    def _ensure_monomorphized_struct(self, struct_name: str, type_args: List[SawType]) -> str:
        """Ensure a monomorphized version of a generic struct exists.
        Returns the mangled name of the monomorphized struct."""
        mangled_name = self._mangle_generic_struct_name(struct_name, type_args)

        # Already generated
        if mangled_name in self.struct_types:
            return mangled_name

        # Get the generic struct
        if struct_name not in self.generic_structs:
            raise ValueError(f"Unknown generic struct: {struct_name}")
        generic_struct = self.generic_structs[struct_name]

        # Build type mapping: T -> Int, etc.
        type_mapping = {}
        for i, type_param in enumerate(generic_struct.type_params):
            if i < len(type_args):
                type_mapping[type_param.name] = type_args[i]

        # Set type param context for _get_llvm_type
        old_context = self.type_param_context
        self.type_param_context = type_mapping

        # Generate field types with substitution
        field_types = []
        for field in generic_struct.fields:
            substituted = self._substitute_saw_type(field.type, type_mapping)
            field_types.append(self._get_llvm_type(substituted))

        # Create identified struct type (unique identity even if same field types)
        llvm_struct_type = self.module.context.get_identified_type(mangled_name)
        llvm_struct_type.set_body(*field_types)

        # Store the type and field order
        field_order = [field.name for field in generic_struct.fields]
        self.struct_types[mangled_name] = (llvm_struct_type, field_order)

        # Restore context before generating extensions
        # (extensions will set their own context)
        self.type_param_context = old_context

        # If there's a generic extension for this struct, also monomorphize its methods
        if struct_name in self.generic_extensions:
            self._monomorphize_extension(struct_name, type_args, mangled_name, type_mapping)

        return mangled_name

    def _ensure_monomorphized_enum(self, enum_name: str, type_args: List[SawType]) -> str:
        """Ensure a monomorphized version of a generic enum exists.
        Returns the mangled name of the monomorphized enum."""
        mangled_name = self._mangle_generic_struct_name(enum_name, type_args)

        # Already generated
        if mangled_name in self.enum_types:
            return mangled_name

        # Get the generic enum
        if enum_name not in self.generic_enums:
            raise ValueError(f"Unknown generic enum: {enum_name}")
        generic_enum = self.generic_enums[enum_name]

        # Build type mapping: T -> Int, etc.
        type_mapping = {}
        for i, type_param in enumerate(generic_enum.type_params):
            if i < len(type_args):
                type_mapping[type_param.name] = type_args[i]

        # Set type param context for _get_llvm_type
        old_context = self.type_param_context
        self.type_param_context = type_mapping

        # Create substituted variants
        substituted_variants = []
        for variant in generic_enum.variants:
            substituted_types = []
            for param_name, param_type in variant.associated_types:
                substituted = self._substitute_saw_type(param_type, type_mapping)
                substituted_types.append((param_name, substituted))
            substituted_variants.append(EnumVariant(
                name=variant.name,
                associated_types=substituted_types
            ))

        # Restore context before registering (registration will use _get_llvm_type)
        self.type_param_context = old_context

        # Register the monomorphized enum
        self._register_concrete_enum(mangled_name, substituted_variants)

        return mangled_name

    def _monomorphize_extension(self, struct_name: str, type_args: List[SawType],
                                 mangled_struct_name: str, type_mapping: dict[str, SawType]):
        """Generate monomorphized version of extension methods for a generic struct."""
        # Process all extensions for this struct
        for generic_ext in self.generic_extensions[struct_name]:
            self._monomorphize_single_extension(generic_ext, type_args, mangled_struct_name, type_mapping)

    def _monomorphize_single_extension(self, generic_ext: Extension, type_args: List[SawType],
                                        mangled_struct_name: str, type_mapping: dict[str, SawType]):
        """Generate monomorphized version of a single extension's methods."""

        # Save current state - we may be in the middle of generating another function
        saved_builder = self.builder
        saved_variables = self.variables
        saved_variable_types = self.variable_types.copy() if self.variable_types else {}
        saved_cleanup_stack = self.cleanup_stack[:] if self.cleanup_stack else []

        # Set type param context
        old_context = self.type_param_context
        self.type_param_context = type_mapping

        # First pass: register all methods (so methods can call each other)
        methods_to_generate = []
        for method in generic_ext.methods:
            # Create mangled name using the monomorphized struct name
            if method.is_init:
                param_names = [p.name for p in method.parameters]
                mangled_name = self._mangle_method_name(mangled_struct_name, method.name, param_names)
            else:
                mangled_name = self._mangle_method_name(mangled_struct_name, method.name)

            # Build parameter types with substitution
            if method.is_init:
                param_types = []
                for p in method.parameters:
                    substituted = self._substitute_saw_type(p.type, type_mapping)
                    param_types.append(self._get_llvm_type(substituted))
                struct_type, _ = self.struct_types[mangled_struct_name]
                return_type = struct_type
            else:
                param_types = []
                for i, p in enumerate(method.parameters):
                    if i == 0 and p.name == "self":
                        # Self type is the monomorphized struct
                        llvm_type = self.struct_types[mangled_struct_name][0]
                    else:
                        substituted = self._substitute_saw_type(p.type, type_mapping)
                        llvm_type = self._get_llvm_type(substituted)
                    if i == 0 and p.name == "self" and method.self_mutable:
                        llvm_type = llvm_type.as_pointer()
                    param_types.append(llvm_type)
                substituted_return = self._substitute_saw_type(method.return_type, type_mapping)
                return_type = self._get_llvm_type(substituted_return)

            # Create function type and register
            func_type = ir.FunctionType(return_type, param_types)
            llvm_func = ir.Function(self.module, func_type, name=mangled_name)
            self.functions[mangled_name] = llvm_func
            methods_to_generate.append(method)

        # Second pass: generate method bodies
        for method in methods_to_generate:
            if method.is_init:
                self._generate_init_method_generic(mangled_struct_name, method, type_mapping)
            else:
                self._generate_method_generic(mangled_struct_name, method, type_mapping)

        # Restore all state
        self.type_param_context = old_context
        self.builder = saved_builder
        self.variables = saved_variables
        self.variable_types = saved_variable_types
        self.cleanup_stack = saved_cleanup_stack

    def _generate_method_generic(self, struct_name: str, method: Method, type_mapping: dict[str, SawType]):
        """Generate code for a method with type substitution."""
        mangled_name = self._mangle_method_name(struct_name, method.name)
        llvm_func = self.functions[mangled_name]

        # Create entry block
        block = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(block)

        # Clear variables for this method
        self.variables = {}

        # Set type param context for method body
        old_context = self.type_param_context
        self.type_param_context = type_mapping

        # Create allocas for parameters (including self)
        for i, param in enumerate(method.parameters):
            llvm_func.args[i].name = param.name
            if i == 0 and param.name == "self" and method.self_mutable:
                self.variables[param.name] = llvm_func.args[i]
            else:
                if i == 0 and param.name == "self":
                    param_type = self.struct_types[struct_name][0]
                else:
                    substituted = self._substitute_saw_type(param.type, type_mapping)
                    param_type = self._get_llvm_type(substituted)
                alloca = self.builder.alloca(param_type, name=param.name)
                self.builder.store(llvm_func.args[i], alloca)
                self.variables[param.name] = alloca

        # Generate method body
        result = self._generate_block(method.body)

        # Handle return
        substituted_return = self._substitute_saw_type(method.return_type, type_mapping)
        if substituted_return.kind == TypeKind.VOID:
            if not self.builder.block.is_terminated:
                self.builder.ret_void()
        else:
            if not self.builder.block.is_terminated:
                if result is not None:
                    self.builder.ret(result)
                else:
                    return_type = self._get_llvm_type(substituted_return)
                    self.builder.ret(ir.Constant(return_type, ir.Undefined))

        # Restore context
        self.type_param_context = old_context

    def _generate_init_method_generic(self, struct_name: str, method: Method, type_mapping: dict[str, SawType]):
        """Generate code for an init method with type substitution."""
        param_names = [p.name for p in method.parameters]
        mangled_name = self._mangle_method_name(struct_name, method.name, param_names)
        llvm_func = self.functions[mangled_name]

        # Create entry block
        block = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(block)

        # Clear variables for this method
        self.variables = {}

        # Set type param context
        old_context = self.type_param_context
        self.type_param_context = type_mapping

        # Create allocas for parameters
        for i, param in enumerate(method.parameters):
            llvm_func.args[i].name = param.name
            substituted = self._substitute_saw_type(param.type, type_mapping)
            param_type = self._get_llvm_type(substituted)
            alloca = self.builder.alloca(param_type, name=param.name)
            self.builder.store(llvm_func.args[i], alloca)
            self.variables[param.name] = alloca

        # Generate init body
        result = self._generate_block(method.body)

        # Return the result (should be a struct)
        if not self.builder.block.is_terminated:
            if result is not None:
                self.builder.ret(result)
            else:
                struct_type, _ = self.struct_types[struct_name]
                self.builder.ret(ir.Constant(struct_type, ir.Undefined))

        # Restore context
        self.type_param_context = old_context

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

    def _generate_extension_methods(self, extension: Extension):
        """Generate code for all methods in an extension."""
        # Skip generic extensions - they'll be monomorphized when the struct is used
        if extension.type_params:
            return

        # Set Self type context for this extension
        old_self_context = self.self_type_context
        self.self_type_context = extension.struct_name

        for method in extension.methods:
            if method.is_init:
                self._generate_init_method(extension.struct_name, method)
            elif method.is_static:
                self._generate_static_method(extension.struct_name, method)
            else:
                self._generate_method(extension.struct_name, method)

        # Restore Self type context
        self.self_type_context = old_self_context

    def _generate_method(self, struct_name: str, method: Method):
        """Generate code for a single method."""
        mangled_name = self._mangle_method_name(struct_name, method.name)
        llvm_func = self.functions[mangled_name]

        # Create entry block
        block = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(block)

        # Clear variables and cleanup stack for this method
        self.variables = {}
        self.variable_types = {}
        self.cleanup_stack = []

        # Determine the Self type for this extension
        if struct_name == "String":
            self_llvm_type = ir.IntType(8).as_pointer()  # String is i8*
            self_saw_type = SawType(TypeKind.STRING)
        else:
            self_llvm_type = self.struct_types[struct_name][0]
            self_saw_type = SawType(TypeKind.STRUCT, struct_name=struct_name)

        # Create allocas for parameters (including self)
        for i, param in enumerate(method.parameters):
            llvm_func.args[i].name = param.name
            # For mutable self, it's already a pointer - just store it directly
            if i == 0 and param.name == "self" and method.self_mutable:
                self.variables[param.name] = llvm_func.args[i]
                self.variable_types[param.name] = self_saw_type
            elif param.name == "self":
                # Handle 'self' parameter - use the Self type
                alloca = self.builder.alloca(self_llvm_type, name=param.name)
                self.builder.store(llvm_func.args[i], alloca)
                self.variables[param.name] = alloca
                self.variable_types[param.name] = self_saw_type
            else:
                alloca = self.builder.alloca(self._get_llvm_type(param.type), name=param.name)
                self.builder.store(llvm_func.args[i], alloca)
                self.variables[param.name] = alloca
                self.variable_types[param.name] = param.type

        # Set current return type for implicit optional wrapping
        old_return_type = self.current_return_type
        self.current_return_type = method.return_type

        # Generate method body
        result = self._generate_block(method.body)

        # For deinit methods, auto-call deinit on fields that implement Deinit
        if method.name == "deinit" and not self.builder.block.is_terminated:
            self._generate_field_deinit_calls(struct_name)

        # Handle return
        if method.return_type.kind == TypeKind.VOID:
            if not self.builder.block.is_terminated:
                self.builder.ret_void()
        else:
            if not self.builder.block.is_terminated:
                if result is not None:
                    # Check if we need to wrap the result in an optional
                    expected_type = self._get_llvm_type(method.return_type)
                    if self._is_optional_type(expected_type) and not self._is_optional_type(result.type):
                        # Wrap in Some
                        result = self._wrap_in_optional(result)
                    self.builder.ret(result)
                else:
                    # Return default value
                    default = ir.Constant(self._get_llvm_type(method.return_type), 0)
                    self.builder.ret(default)

        # Restore return type
        self.current_return_type = old_return_type

    def _generate_field_deinit_calls(self, struct_name: str):
        """Generate deinit calls for all fields that implement Deinit.

        Called at the end of a deinit method to ensure nested resources are cleaned up.
        Fields are cleaned up in reverse declaration order.
        """
        # Use namespace for struct field types
        field_types = self.namespace.get_struct_fields(struct_name)
        if not field_types:
            return
        _, field_order = self.struct_types[struct_name]

        # Get self pointer
        self_ptr = self.variables.get("self")
        if self_ptr is None:
            return

        # Process fields in reverse order
        for field_name in reversed(field_order):
            field_type = field_types.get(field_name)
            if field_type is None:
                continue

            # Check if this field type needs deinit
            behavior = self._get_cleanup_behavior(field_type)
            if behavior == "none":
                continue

            # Get the field's type name for method lookup
            type_name = self._get_type_name_for_conformance(field_type)
            if type_name is None:
                continue

            # Check if deinit method exists
            deinit_method_name = self._mangle_method_name(type_name, "deinit")
            if deinit_method_name not in self.functions:
                continue

            deinit_fn = self.functions[deinit_method_name]

            # Get pointer to field
            field_index = field_order.index(field_name)
            field_ptr = self.builder.gep(self_ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), field_index)
            ], name=f"{field_name}_ptr")

            # Call deinit on the field (deinit takes var self = pointer)
            self.builder.call(deinit_fn, [field_ptr])

    def _generate_init_method(self, struct_name: str, method: Method):
        """Generate code for a custom init method."""
        param_names = [p.name for p in method.parameters]
        mangled_name = self._mangle_method_name(struct_name, method.name, param_names)
        llvm_func = self.functions[mangled_name]

        # Create entry block
        block = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(block)

        # Clear variables and cleanup stack for this method
        self.variables = {}
        self.variable_types = {}
        self.cleanup_stack = []

        # Set current return type for None literal generation
        old_return_type = self.current_return_type
        self.current_return_type = method.return_type

        # Create allocas for parameters (no self for init methods)
        for i, param in enumerate(method.parameters):
            llvm_func.args[i].name = param.name
            alloca = self.builder.alloca(self._get_llvm_type(param.type), name=param.name)
            self.builder.store(llvm_func.args[i], alloca)
            self.variables[param.name] = alloca
            self.variable_types[param.name] = param.type

        # Generate method body - must return a struct value
        result = self._generate_block(method.body)

        # Handle return - init methods must return the struct
        if not self.builder.block.is_terminated:
            if result is not None:
                self.builder.ret(result)
            else:
                # Error: init must return a struct
                # For now, return a default struct value
                struct_type, _ = self.struct_types[struct_name]
                default = ir.Constant(struct_type, ir.Undefined)
                self.builder.ret(default)

        # Restore previous return type
        self.current_return_type = old_return_type

    def _generate_static_method(self, struct_name: str, method: Method):
        """Generate code for a static method (no self parameter)."""
        mangled_name = self._mangle_method_name(struct_name, method.name)
        llvm_func = self.functions[mangled_name]

        # Create entry block
        block = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(block)

        # Clear variables and cleanup stack for this method
        self.variables = {}
        self.variable_types = {}
        self.cleanup_stack = []

        # Set current return type for None literal generation
        old_return_type = self.current_return_type
        self.current_return_type = method.return_type

        # Create allocas for parameters (no self for static methods)
        for i, param in enumerate(method.parameters):
            llvm_func.args[i].name = param.name
            alloca = self.builder.alloca(self._get_llvm_type(param.type), name=param.name)
            self.builder.store(llvm_func.args[i], alloca)
            self.variables[param.name] = alloca
            self.variable_types[param.name] = param.type

        # Generate method body
        result = self._generate_block(method.body)

        # Handle return
        if not self.builder.block.is_terminated:
            if method.return_type.kind == TypeKind.VOID:
                self.builder.ret_void()
            elif result is not None:
                # Check if we need to wrap in Some (T -> T?)
                expected_type = self._get_llvm_type(method.return_type)
                if (method.return_type.is_optional() and
                    self._is_optional_type(expected_type) and
                    not self._is_optional_type(result.type)):
                    result = self._wrap_in_optional(result)
                self.builder.ret(result)
            else:
                self.builder.ret_void()

        # Restore previous return type
        self.current_return_type = old_return_type

    def _generate_function(self, func: Function, name_override: str = None):
        """Generate a function body. If name_override is provided, use it instead of func.name."""
        func_name = name_override if name_override else func.name
        llvm_func = self.functions[func_name]

        # Create entry block
        block = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(block)

        # Clear variables and cleanup stack for this function
        self.variables = {}
        self.variable_types = {}
        self.cleanup_stack = []

        # Set current return type for None literal generation
        old_return_type = self.current_return_type
        self.current_return_type = func.return_type

        # Create allocas for parameters and track for cleanup
        # Push a scope for function parameters (cleaned up when function returns)
        self.cleanup_stack.append([])
        for i, param in enumerate(func.parameters):
            llvm_func.args[i].name = param.name
            alloca = self.builder.alloca(self._get_llvm_type(param.type), name=param.name)
            self.builder.store(llvm_func.args[i], alloca)
            self.variables[param.name] = alloca
            self.variable_types[param.name] = param.type
            # Track parameter for cleanup if it needs it
            if self._needs_cleanup(param.type):
                self.cleanup_stack[-1].append((param.name, param.type))

        # Generate function body (block manages its own cleanup scope)
        result = self._generate_block(func.body)

        # Handle return - cleanup parameter scope before returning
        if func.return_type.kind == TypeKind.VOID:
            if not self.builder.block.is_terminated:
                # Cleanup parameter scope before return
                self._cleanup_all_scopes()
                # For main(), return 0 instead of void
                if func.name == "main":
                    self.builder.ret(ir.Constant(ir.IntType(32), 0))
                else:
                    self.builder.ret_void()
        else:
            if not self.builder.block.is_terminated:
                # Cleanup parameter scope before return
                self._cleanup_all_scopes()
                if result is not None:
                    # Check if we need to wrap in Some (T -> T?)
                    expected_type = self._get_llvm_type(func.return_type)
                    if (func.return_type.is_optional() and
                        self._is_optional_type(expected_type) and
                        not self._is_optional_type(result.type)):
                        # Wrap in Some
                        result = self._wrap_in_optional(result)
                    self.builder.ret(result)
                else:
                    # Return default value
                    default = ir.Constant(self._get_llvm_type(func.return_type), 0)
                    self.builder.ret(default)

        # Restore previous return type
        self.current_return_type = old_return_type

    def _generate_block(self, block: Block, manage_cleanup: bool = True):
        """Generate code for a block.

        Args:
            block: The block to generate code for
            manage_cleanup: If True, push/pop a cleanup scope for this block.
                          Set to False when the caller manages cleanup (e.g., functions).
        """
        # Push new cleanup scope for this block
        if manage_cleanup:
            self.cleanup_stack.append([])

        result = None

        for stmt in block.statements:
            self._generate_statement(stmt)
            if self.builder.block.is_terminated:
                # Early exit (return/break) already handled cleanup
                if manage_cleanup:
                    self.cleanup_stack.pop()
                return None

        if block.final_expr is not None:
            result = self._generate_expression(block.final_expr)

        # Cleanup variables declared in this block
        if manage_cleanup:
            scope_vars = self.cleanup_stack.pop()
            if not self.builder.block.is_terminated:
                self._cleanup_scope(scope_vars)

        return result

    def _generate_statement(self, stmt: Statement):
        """Generate code for a statement."""
        # Handle dual-purpose nodes (Expressions used as Statements)
        if isinstance(stmt, WhileExpr):
            self._generate_while_expr(stmt)
            return
        if isinstance(stmt, ForLoop):
            self._generate_for_loop(stmt)
            return

        # Visitor dispatch for all other statements
        method_name = f'visit_{stmt.__class__.__name__}'
        visitor = getattr(self, method_name, None)
        if visitor is None:
            raise ValueError(f"Unknown statement type: {type(stmt)}")
        visitor(stmt)

    # ===== Statement Visitor Methods =====

    def visit_LetStatement(self, stmt: LetStatement):
        self._generate_let_statement(stmt)

    def visit_AssignStatement(self, stmt: AssignStatement):
        self._generate_assign_statement(stmt)

    def visit_ReturnStatement(self, stmt: ReturnStatement):
        self._generate_return_statement(stmt)

    def visit_GuardLetStatement(self, stmt: GuardLetStatement):
        self._generate_guard_let_statement(stmt)

    def visit_BreakStatement(self, stmt: BreakStatement):
        self._generate_break_statement(stmt)

    def visit_ContinueStatement(self, stmt: ContinueStatement):
        self._generate_continue_statement(stmt)

    def visit_ExpressionStatement(self, stmt: ExpressionStatement):
        # Expression used as statement - we don't need its result value
        self._generate_expression(stmt.expression, need_result=False)

    def _generate_let_statement(self, stmt: LetStatement):
        value = self._generate_expression(stmt.value)

        # Resolve type alias in annotation
        resolved_annotation = self._resolve_type_alias(stmt.type_annotation) if stmt.type_annotation else None

        # Determine the variable type early for copy behavior
        var_type = resolved_annotation if resolved_annotation else self._infer_saw_type(stmt.value)

        # Apply copy behavior for CustomCopy types when initializing from an existing value
        # (not for fresh struct/enum construction which doesn't need copying)
        # Skip copy for move expressions - ownership is transferred, not copied
        if var_type and isinstance(stmt.value, Identifier) and not isinstance(stmt.value, MoveExpr):
            value = self._generate_copy(value, var_type)

        # Check if we need to wrap the value in an optional
        if resolved_annotation and resolved_annotation.kind == TypeKind.OPTIONAL:
            # Check if value is not already optional
            # An optional is a struct with first element being i1 (is_some flag)
            is_already_optional = (isinstance(value.type, ir.LiteralStructType) and
                                   len(value.type.elements) == 2 and
                                   isinstance(value.type.elements[0], ir.IntType) and
                                   value.type.elements[0].width == 1)

            if not is_already_optional:
                # Wrap the value in an optional
                value = self._wrap_in_optional(value)
            else:
                # Value is already optional, but check if it's a None literal with i64 placeholder
                # that needs to be converted to match a different expected type
                current_inner_type = value.type.elements[1]
                target_inner_type = self._get_llvm_type(resolved_annotation.inner_type)

                # Only convert if current is i64 (None literal placeholder) and target is something else
                needs_conversion = (isinstance(current_inner_type, ir.IntType) and
                                    current_inner_type.width == 64 and
                                    not (isinstance(target_inner_type, ir.IntType) and
                                         target_inner_type.width == 64))

                if needs_conversion:
                    # This is a None literal (i64 placeholder) being assigned to a different optional type
                    correct_optional_type = ir.LiteralStructType([ir.IntType(1), target_inner_type])

                    # Extract is_some flag (should be false for None)
                    is_some = self.builder.extract_value(value, 0, name="is_some")

                    # Create new optional with correct type
                    new_optional = ir.Constant(correct_optional_type, ir.Undefined)
                    new_optional = self.builder.insert_value(new_optional, is_some, 0)
                    # Don't set the value - it's undef for None anyway

                    value = new_optional

        alloca = self.builder.alloca(value.type, name=stmt.name)
        self.builder.store(value, alloca)
        self.variables[stmt.name] = alloca

        # Track variable type for resource management
        if var_type:
            self.variable_types[stmt.name] = var_type
            # Track for cleanup if type implements Deinit/CustomCopy/NoCopy
            if self.cleanup_stack and self._needs_cleanup(var_type):
                self.cleanup_stack[-1].append((stmt.name, var_type))

    def _infer_saw_type(self, expr) -> Optional[SawType]:
        """Infer the SawType of an expression (basic inference for common cases)."""
        if isinstance(expr, IntLiteral):
            return SawType(TypeKind.INT)
        elif isinstance(expr, FloatLiteral):
            return SawType(TypeKind.FLOAT)
        elif isinstance(expr, BoolLiteral):
            return SawType(TypeKind.BOOL)
        elif isinstance(expr, StringLiteral):
            return SawType(TypeKind.STRING)
        elif isinstance(expr, StringInterpolation):
            return SawType(TypeKind.STRING)
        elif isinstance(expr, StructInit):
            return SawType(TypeKind.STRUCT, struct_name=expr.struct_name, type_args=expr.type_args)
        elif isinstance(expr, EnumInit):
            return SawType(TypeKind.ENUM, enum_name=expr.enum_name, type_args=expr.type_args)
        elif isinstance(expr, Identifier):
            # Look up variable type
            return self.variable_types.get(expr.name)
        elif isinstance(expr, MoveExpr):
            # Look up the moved variable's type
            return self.variable_types.get(expr.variable)
        elif isinstance(expr, CastExpr):
            # Cast expression returns the target type
            return expr.target_type
        elif isinstance(expr, FunctionCall):
            # Check if this is a struct init (parser treats Struct() as function call)
            if expr.name in self.struct_types or expr.name in self.generic_structs:
                return SawType(TypeKind.STRUCT, struct_name=expr.name, type_args=expr.type_args)
            # Check if it's a known function (use namespace)
            return_type = self.namespace.get_return_type(expr.name)
            if return_type:
                return return_type
            return None
        elif isinstance(expr, MethodCall):
            # Check for static method call: StructName.method() (use namespace)
            if isinstance(expr.object, Identifier):
                struct_name = expr.object.name
                if self.namespace.is_static_method(struct_name, expr.method_name):
                    return_type = self.namespace.get_method_return_type(struct_name, expr.method_name)
                    if return_type:
                        return return_type
            # Look up the method return type for instance methods (use namespace)
            obj_type = self._infer_saw_type(expr.object)
            if obj_type and obj_type.kind == TypeKind.STRUCT:
                struct_name = obj_type.struct_name
                return_type = self.namespace.get_method_return_type(struct_name, expr.method_name)
                if return_type:
                    return return_type
            return None
        elif isinstance(expr, MemberAccess):
            # Look up struct field type (use namespace)
            obj_type = self._infer_saw_type(expr.object)
            if obj_type and obj_type.kind == TypeKind.STRUCT:
                struct_name = obj_type.struct_name
                field_types = self.namespace.get_struct_fields(struct_name)
                if field_types and expr.member in field_types:
                    return field_types[expr.member]
            return None
        elif isinstance(expr, BinaryOp):
            # Infer type from binary operations
            if expr.op in ('==', '!=', '<', '>', '<=', '>=', '&&', '||'):
                return SawType(TypeKind.BOOL)
            elif expr.op in ('+', '-', '*', '/', '%'):
                left_type = self._infer_saw_type(expr.left)
                right_type = self._infer_saw_type(expr.right)
                # Float takes precedence
                if left_type and left_type.kind == TypeKind.FLOAT:
                    return SawType(TypeKind.FLOAT)
                if right_type and right_type.kind == TypeKind.FLOAT:
                    return SawType(TypeKind.FLOAT)
                # Default to Int for arithmetic
                if left_type:
                    return left_type
                if right_type:
                    return right_type
                return SawType(TypeKind.INT)
            return None
        elif isinstance(expr, UnaryOp):
            if expr.op == 'not':
                return SawType(TypeKind.BOOL)
            return self._infer_saw_type(expr.operand)
        return None

    def _generate_assign_statement(self, stmt: AssignStatement):
        value = self._generate_expression(stmt.value)

        if isinstance(stmt.target, Identifier):
            # Simple variable assignment
            if stmt.target.name not in self.variables:
                raise ValueError(f"Undefined variable: {stmt.target.name}")

            # Get the variable's type for resource management
            var_type = self.variable_types.get(stmt.target.name)

            if var_type:
                # Call deinit on the old value before overwriting
                if self._needs_cleanup(var_type):
                    self._generate_deinit_call(stmt.target.name, var_type)

                # Apply copy behavior for CustomCopy types
                if isinstance(stmt.value, Identifier):
                    value = self._generate_copy(value, var_type)

                # Wrap in optional if assigning T to T?
                expected_type = self._get_llvm_type(var_type)
                if (var_type.is_optional() and
                    self._is_optional_type(expected_type) and
                    not self._is_optional_type(value.type)):
                    value = self._wrap_in_optional(value)

            self.builder.store(value, self.variables[stmt.target.name])

        elif isinstance(stmt.target, MemberAccess):
            # Field assignment: obj.field = value
            # We need to get a pointer to the object first
            obj_expr = stmt.target.object

            # Get pointer to the struct
            if isinstance(obj_expr, Identifier):
                # Direct variable reference: p.x = value
                if obj_expr.name not in self.variables:
                    raise ValueError(f"Undefined variable: {obj_expr.name}")
                struct_ptr = self.variables[obj_expr.name]
            elif isinstance(obj_expr, SelfExpr):
                # self.field = value
                struct_ptr = self.variables["self"]
            elif isinstance(obj_expr, ArrayIndex):
                # Array/pointer indexing: arr[i].field = value or ptr[i].field = value
                container_val = self._generate_expression(obj_expr.array_expr)
                index_val = self._generate_expression(obj_expr.index)

                if isinstance(container_val.type, ir.PointerType):
                    # Pointer indexing: ptr[i].field = value
                    struct_ptr = self.builder.gep(container_val, [index_val], name="ptr_idx")
                elif isinstance(container_val.type, ir.ArrayType):
                    # Array indexing - need to allocate, store, and use GEP
                    array_ptr = self.builder.alloca(container_val.type, name="arr_tmp")
                    self.builder.store(container_val, array_ptr)
                    zero = ir.Constant(ir.IntType(64), 0)
                    struct_ptr = self.builder.gep(array_ptr, [zero, index_val], name="elem_ptr")
                else:
                    raise ValueError(f"Cannot index into type for field assignment: {container_val.type}")
            else:
                raise ValueError(f"Unsupported object expression in field assignment: {type(obj_expr)}")

            # Determine struct type and field index
            # Get the actual struct type (dereference if it's a pointer)
            pointee_type = struct_ptr.type.pointee

            # Find which struct this is
            struct_name = None
            if hasattr(pointee_type, 'name') and pointee_type.name in self.struct_types:
                # Identified type - name is directly available
                struct_name = pointee_type.name
            else:
                # Fallback to string comparison for literal types
                for name, (st, _) in self.struct_types.items():
                    if str(st) == str(pointee_type):
                        struct_name = name
                        break

            if not struct_name:
                raise ValueError("Cannot determine struct type for field assignment")

            # Get field index
            _, field_order = self.struct_types[struct_name]
            if stmt.target.member not in field_order:
                raise ValueError(f"Struct {struct_name} has no field {stmt.target.member}")

            field_index = field_order.index(stmt.target.member)

            # Generate GEP to get pointer to field
            field_ptr = self.builder.gep(struct_ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), field_index)
            ], name=f"{stmt.target.member}_ptr")

            # Check if we need to wrap in optional (non-optional value for optional field)
            expected_field_type = field_ptr.type.pointee
            if isinstance(expected_field_type, ir.LiteralStructType) and len(expected_field_type.elements) == 2:
                # Expected is optional {i1, T}, check if value needs wrapping
                if not isinstance(value.type, ir.LiteralStructType):
                    value = self._wrap_in_optional(value)

            # Store value to field
            self.builder.store(value, field_ptr)

        elif isinstance(stmt.target, ArrayIndex):
            # Array or pointer element assignment: arr[i] = value or ptr[i] = value
            container_expr = stmt.target.array_expr
            index_val = self._generate_expression(stmt.target.index)

            # Get pointer to the container
            if isinstance(container_expr, Identifier):
                if container_expr.name not in self.variables:
                    raise ValueError(f"Undefined variable: {container_expr.name}")
                container_ptr = self.variables[container_expr.name]

                # Load the container value to check its type
                container_val = self.builder.load(container_ptr, name="container")

                if isinstance(container_val.type, ir.ArrayType):
                    # Array: GEP with two indices [0, index]
                    zero = ir.Constant(ir.IntType(64), 0)
                    elem_ptr = self.builder.gep(container_ptr, [zero, index_val], name="elem_ptr")
                elif isinstance(container_val.type, ir.PointerType):
                    # Pointer: GEP with single index
                    elem_ptr = self.builder.gep(container_val, [index_val], name="ptr_elem")
                else:
                    raise ValueError(f"Cannot index into type: {container_val.type}")
            else:
                raise ValueError(f"Unsupported container expression in assignment: {type(container_expr)}")

            # Coerce value type if needed (e.g., Int -> Int8)
            elem_type = elem_ptr.type.pointee
            if isinstance(value.type, ir.IntType) and isinstance(elem_type, ir.IntType):
                if value.type.width > elem_type.width:
                    # Truncate larger int to smaller
                    value = self.builder.trunc(value, elem_type, name="trunc")
                elif value.type.width < elem_type.width:
                    # Extend smaller int to larger (sign extend)
                    value = self.builder.sext(value, elem_type, name="sext")

            # Store value to element
            self.builder.store(value, elem_ptr)

        else:
            raise ValueError(f"Invalid assignment target: {type(stmt.target)}")

    def _generate_return_statement(self, stmt: ReturnStatement):
        # Generate return value first (before cleanup, in case it uses local vars)
        if stmt.value is not None:
            value = self._generate_expression(stmt.value)
        else:
            value = None

        # Cleanup all scopes before returning
        self._cleanup_all_scopes()

        # Now return
        if value is not None:
            # Check if we need to wrap in optional
            if self.current_return_type and self.current_return_type.is_optional():
                expected_type = self._get_llvm_type(self.current_return_type)
                if not self._is_optional_type(value.type):
                    value = self._wrap_in_optional(value)

            self.builder.ret(value)
        else:
            self.builder.ret_void()

    def _generate_while_expr(self, stmt: WhileExpr):
        """Generate LLVM IR for a while loop (statement context)."""
        func = self.builder.function

        # Create basic blocks
        cond_block = func.append_basic_block("while.cond")
        body_block = func.append_basic_block("while.body")
        end_block = func.append_basic_block("while.end")

        # Push loop blocks onto stack for break/continue (no result storage)
        self.loop_stack.append((cond_block, end_block, None))

        # Jump to condition block
        self.builder.branch(cond_block)

        # Generate condition
        self.builder.position_at_end(cond_block)
        if stmt.condition:
            # Conditional while
            cond_value = self._generate_expression(stmt.condition)
            self.builder.cbranch(cond_value, body_block, end_block)
        else:
            # Infinite loop (while { })
            self.builder.branch(body_block)

        # Generate body
        self.builder.position_at_end(body_block)
        self._generate_block(stmt.body)
        # If block doesn't end with terminator, loop back to condition
        if not self.builder.block.is_terminated:
            self.builder.branch(cond_block)

        # Pop loop blocks
        self.loop_stack.pop()

        # Position at end block for next statements
        self.builder.position_at_end(end_block)

    def _generate_for_loop(self, stmt: ForLoop):
        """Generate LLVM IR for a for loop using Iterator.

        Desugars: for i in start..end { body }
        Into:     var __range = Range(current: start, end: end)
                  while let i = __range.next() {
                      body
                  }

        Or for custom iterators:
        Desugars: for i in iterator { body }
        Into:     var __iter = iterator
                  while let i = __iter.next() {
                      body
                  }
        """
        func = self.builder.function

        if isinstance(stmt.iterable, RangeExpr):
            # Range expression: use builtin Range type
            range_expr = stmt.iterable
            start_val = self._generate_expression(range_expr.start)
            end_val = self._generate_expression(range_expr.end)

            # Create the Range struct: { current, end }
            range_type, _ = self.struct_types["Range"]
            iter_alloca = self.builder.alloca(range_type, name="__range")

            # Initialize Range with start and end
            range_val = ir.Constant(range_type, ir.Undefined)
            range_val = self.builder.insert_value(range_val, start_val, 0)
            range_val = self.builder.insert_value(range_val, end_val, 1)
            self.builder.store(range_val, iter_alloca)

            next_func = self.functions["Range_next"]
            item_type = ir.IntType(64)
        else:
            # Custom iterator: generate the iterator expression and call its next() method
            iter_val = self._generate_expression(stmt.iterable)

            # Find the struct type for the iterator
            struct_name = self._find_struct_name_for_value(iter_val)
            if struct_name is None:
                raise ValueError(f"Cannot determine iterator type for for loop")

            # Get the mangled next method name
            next_mangled = self._mangle_method_name(struct_name, "next")
            if next_mangled not in self.functions:
                raise ValueError(f"Type {struct_name} does not implement Iterator (missing next method)")

            next_func = self.functions[next_mangled]

            # Allocate storage for the iterator (since next mutates it)
            iter_alloca = self.builder.alloca(iter_val.type, name="__iter")
            self.builder.store(iter_val, iter_alloca)

            # Determine the item type from the next method's return type
            # next() returns Optional<Item>, so extract Item type from { i1, Item }
            optional_type = next_func.function_type.return_type
            item_type = optional_type.elements[1]

        # Create basic blocks
        cond_block = func.append_basic_block("for.cond")
        body_block = func.append_basic_block("for.body")
        end_block = func.append_basic_block("for.end")

        # Push loop blocks onto stack for break/continue
        # continue goes to cond block (call next again), break goes to end
        self.loop_stack.append((cond_block, end_block, None))

        # Jump to condition block
        self.builder.branch(cond_block)

        # Generate condition: call next() and check if Some
        self.builder.position_at_end(cond_block)
        optional_result = self.builder.call(next_func, [iter_alloca], name="next_result")

        # Extract is_some flag
        is_some = self.builder.extract_value(optional_result, 0, name="is_some")
        self.builder.cbranch(is_some, body_block, end_block)

        # Generate body
        self.builder.position_at_end(body_block)

        # Extract value and create loop variable
        loop_val = self.builder.extract_value(optional_result, 1, name="loop_val")
        loop_var_alloca = self.builder.alloca(item_type, name=stmt.variable)
        self.builder.store(loop_val, loop_var_alloca)
        self.variables[stmt.variable] = loop_var_alloca

        # Generate body block
        self._generate_block(stmt.body)

        # If block doesn't end with terminator, go back to condition
        if not self.builder.block.is_terminated:
            self.builder.branch(cond_block)

        # Pop loop blocks
        self.loop_stack.pop()

        # Clean up loop variable from scope
        del self.variables[stmt.variable]

        # Position at end block for next statements
        self.builder.position_at_end(end_block)

    def _find_struct_name_for_value(self, val) -> Optional[str]:
        """Find the struct name for an LLVM value by matching its type."""
        val_type = val.type
        if isinstance(val_type, ir.PointerType):
            val_type = val_type.pointee

        # For identified types, get name directly
        if hasattr(val_type, 'name') and val_type.name in self.struct_types:
            return val_type.name

        # Fallback to string comparison for literal types
        for name, (llvm_type, _) in self.struct_types.items():
            if str(val_type) == str(llvm_type):
                return name
        return None

    def _generate_for_loop_value(self, expr: ForLoop):
        """Generate LLVM IR for a for loop that returns a value (expression context).

        For loops are always conditional, so they return Optional<T>.
        Uses Iterator interface internally.
        """
        func = self.builder.function

        if isinstance(expr.iterable, RangeExpr):
            # Range expression: use builtin Range type
            range_expr = expr.iterable
            start_val = self._generate_expression(range_expr.start)
            end_val = self._generate_expression(range_expr.end)

            # Create the Range struct: { current, end }
            range_type, _ = self.struct_types["Range"]
            iter_alloca = self.builder.alloca(range_type, name="__range")

            # Initialize Range with start and end
            range_val = ir.Constant(range_type, ir.Undefined)
            range_val = self.builder.insert_value(range_val, start_val, 0)
            range_val = self.builder.insert_value(range_val, end_val, 1)
            self.builder.store(range_val, iter_alloca)

            next_func = self.functions["Range_next"]
            item_type = ir.IntType(64)
        else:
            # Custom iterator: generate the iterator expression and call its next() method
            iter_val = self._generate_expression(expr.iterable)

            # Find the struct type for the iterator
            struct_name = self._find_struct_name_for_value(iter_val)
            if struct_name is None:
                raise ValueError(f"Cannot determine iterator type for for loop")

            # Get the mangled next method name
            next_mangled = self._mangle_method_name(struct_name, "next")
            if next_mangled not in self.functions:
                raise ValueError(f"Type {struct_name} does not implement Iterator (missing next method)")

            next_func = self.functions[next_mangled]

            # Allocate storage for the iterator (since next mutates it)
            iter_alloca = self.builder.alloca(iter_val.type, name="__iter")
            self.builder.store(iter_val, iter_alloca)

            # Determine the item type from the next method's return type
            # next() returns Optional<Item>, so extract Item type from { i1, Item }
            optional_type = next_func.function_type.return_type
            item_type = optional_type.elements[1]

        # For loops are conditional, return Optional<T>
        # Get the inner type from typechecker annotation
        if expr.result_type is not None and expr.result_type.kind == TypeKind.OPTIONAL:
            inner_type = self._get_llvm_type(expr.result_type.inner_type)
        else:
            # Fallback if no type annotation
            inner_type = ir.IntType(64)
        optional_result_type = ir.LiteralStructType([ir.IntType(1), inner_type])
        result_alloca = self.builder.alloca(optional_result_type, name="for.result")

        # Initialize to None (has_value = false, value = 0)
        none_value = ir.Constant(optional_result_type, [ir.Constant(ir.IntType(1), 0), ir.Constant(inner_type, 0)])
        self.builder.store(none_value, result_alloca)

        # Create basic blocks
        cond_block = func.append_basic_block("for.cond")
        body_block = func.append_basic_block("for.body")
        end_block = func.append_basic_block("for.end")

        # Push loop info with result storage
        # continue goes to cond block (call next again), break goes to end
        self.loop_stack.append((cond_block, end_block, result_alloca))

        # Jump to condition block
        self.builder.branch(cond_block)

        # Generate condition: call next() and check if Some
        self.builder.position_at_end(cond_block)
        optional_result = self.builder.call(next_func, [iter_alloca], name="next_result")

        # Extract is_some flag
        is_some = self.builder.extract_value(optional_result, 0, name="is_some")
        self.builder.cbranch(is_some, body_block, end_block)

        # Generate body
        self.builder.position_at_end(body_block)

        # Extract value and create loop variable
        loop_val = self.builder.extract_value(optional_result, 1, name="loop_val")
        loop_var_alloca = self.builder.alloca(item_type, name=expr.variable)
        self.builder.store(loop_val, loop_var_alloca)
        self.variables[expr.variable] = loop_var_alloca

        # Generate body block
        self._generate_block(expr.body)

        # If block doesn't end with terminator, go back to condition
        if not self.builder.block.is_terminated:
            self.builder.branch(cond_block)

        # Pop loop info
        self.loop_stack.pop()

        # Clean up loop variable from scope
        del self.variables[expr.variable]

        # Load and return result
        self.builder.position_at_end(end_block)
        return self.builder.load(result_alloca, name="for.value")

    def _generate_while_expr_value(self, expr: WhileExpr):
        """Generate LLVM IR for a while loop that returns a value (expression context)."""
        func = self.builder.function

        is_conditional = expr.condition is not None

        # Get the result type from typechecker annotation
        if expr.result_type is not None:
            if is_conditional and expr.result_type.kind == TypeKind.OPTIONAL:
                # Conditional loop: result_type is Optional<T>, extract inner type
                inner_type = self._get_llvm_type(expr.result_type.inner_type)
            elif is_conditional:
                # Fallback for void result
                inner_type = ir.IntType(64)
            else:
                # Infinite loop: result_type is T directly
                inner_type = self._get_llvm_type(expr.result_type)
        else:
            # Fallback if no type annotation
            inner_type = ir.IntType(64)

        if is_conditional:
            # Conditional loop returns Optional<T>
            # Optional is { i1 has_value, T value }
            optional_type = ir.LiteralStructType([ir.IntType(1), inner_type])
            result_alloca = self.builder.alloca(optional_type, name="while.result")

            # Initialize to None (has_value = false, value = 0)
            none_value = ir.Constant(optional_type, [ir.Constant(ir.IntType(1), 0), ir.Constant(inner_type, 0)])
            self.builder.store(none_value, result_alloca)
        else:
            # Infinite loop returns T directly
            result_alloca = self.builder.alloca(inner_type, name="while.result")

        # Create basic blocks
        cond_block = func.append_basic_block("while.cond")
        body_block = func.append_basic_block("while.body")
        end_block = func.append_basic_block("while.end")

        # Push loop info with result storage
        self.loop_stack.append((cond_block, end_block, result_alloca))

        # Jump to condition block
        self.builder.branch(cond_block)

        # Generate condition
        self.builder.position_at_end(cond_block)
        if expr.condition:
            cond_value = self._generate_expression(expr.condition)
            self.builder.cbranch(cond_value, body_block, end_block)
        else:
            self.builder.branch(body_block)

        # Generate body
        self.builder.position_at_end(body_block)
        self._generate_block(expr.body)
        if not self.builder.block.is_terminated:
            self.builder.branch(cond_block)

        # Pop loop info
        self.loop_stack.pop()

        # Load and return result
        self.builder.position_at_end(end_block)
        return self.builder.load(result_alloca, name="while.value")

    def _generate_break_statement(self, stmt: BreakStatement):
        """Generate LLVM IR for a break statement."""
        if not self.loop_stack:
            raise ValueError("break outside of loop")

        _, break_block, result_storage = self.loop_stack[-1]

        # If there's a break value and result storage, store it
        if stmt.value and result_storage:
            value = self._generate_expression(stmt.value)

            # Check if result storage is for an Optional type (conditional loop)
            storage_type = result_storage.type.pointee
            if isinstance(storage_type, ir.LiteralStructType) and len(storage_type.elements) == 2:
                # It's an Optional - wrap the value
                # Create Some(value) = { has_value: true, value: value }
                # Start with an undef struct
                some_value = ir.Constant(storage_type, ir.Undefined)
                # Insert has_value = true at index 0
                some_value = self.builder.insert_value(some_value, ir.Constant(ir.IntType(1), 1), 0, name="optional.has_value")
                # Insert the actual value at index 1
                some_value = self.builder.insert_value(some_value, value, 1, name="optional.value")
                self.builder.store(some_value, result_storage)
            else:
                # Direct value storage (infinite loop)
                self.builder.store(value, result_storage)

        # Jump to the break block (end of loop)
        self.builder.branch(break_block)

    def _generate_continue_statement(self, stmt: ContinueStatement):
        """Generate LLVM IR for a continue statement."""
        if not self.loop_stack:
            raise ValueError("continue outside of loop")

        # Jump to the continue block (condition check)
        continue_block, _, _ = self.loop_stack[-1]
        self.builder.branch(continue_block)

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

        elif saw_type.kind in {TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64}:
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

    def _generate_binary_op(self, expr: BinaryOp):
        # Handle short-circuit logical operators specially
        if expr.op == '&&':
            return self._generate_logical_and(expr)
        elif expr.op == '||':
            return self._generate_logical_or(expr)

        left = self._generate_expression(expr.left)
        right = self._generate_expression(expr.right)

        # Check if we're dealing with floats
        is_float = isinstance(left.type, ir.DoubleType)

        if expr.op == '+':
            if isinstance(left.type, ir.PointerType):
                # Pointer arithmetic: ptr + offset
                return self.builder.gep(left, [right], name="ptr_add")
            if is_float:
                return self.builder.fadd(left, right, name="addtmp")
            return self.builder.add(left, right, name="addtmp")

        elif expr.op == '-':
            if isinstance(left.type, ir.PointerType):
                # Pointer arithmetic: ptr - offset (negate offset and add)
                neg_right = self.builder.neg(right, name="neg_offset")
                return self.builder.gep(left, [neg_right], name="ptr_sub")
            if is_float:
                return self.builder.fsub(left, right, name="subtmp")
            return self.builder.sub(left, right, name="subtmp")

        elif expr.op == '*':
            if is_float:
                return self.builder.fmul(left, right, name="multmp")
            return self.builder.mul(left, right, name="multmp")

        elif expr.op == '/':
            if is_float:
                return self.builder.fdiv(left, right, name="divtmp")
            return self.builder.sdiv(left, right, name="divtmp")

        elif expr.op == '%':
            # Modulo only works on integers
            return self.builder.srem(left, right, name="modtmp")

        elif expr.op == '==':
            # Check if we're comparing enum types (tag-only comparison)
            if isinstance(left.type, ir.LiteralStructType) and len(left.type.elements) == 2:
                # Might be an enum with payload: {i32, [N x i8]}
                if isinstance(left.type.elements[0], ir.IntType) and left.type.elements[0].width == 32:
                    # Extract tags and compare
                    left_tag = self.builder.extract_value(left, 0, name="left_tag")
                    right_tag = self.builder.extract_value(right, 0, name="right_tag")
                    return self.builder.icmp_signed('==', left_tag, right_tag, name="eqtmp")

            if is_float:
                return self.builder.fcmp_ordered('==', left, right, name="eqtmp")
            return self.builder.icmp_signed('==', left, right, name="eqtmp")

        elif expr.op == '!=':
            # Check if we're comparing enum types (tag-only comparison)
            if isinstance(left.type, ir.LiteralStructType) and len(left.type.elements) == 2:
                # Might be an enum with payload: {i32, [N x i8]}
                if isinstance(left.type.elements[0], ir.IntType) and left.type.elements[0].width == 32:
                    # Extract tags and compare
                    left_tag = self.builder.extract_value(left, 0, name="left_tag")
                    right_tag = self.builder.extract_value(right, 0, name="right_tag")
                    return self.builder.icmp_signed('!=', left_tag, right_tag, name="netmp")

            if is_float:
                return self.builder.fcmp_ordered('!=', left, right, name="netmp")
            return self.builder.icmp_signed('!=', left, right, name="netmp")

        elif expr.op == '<':
            if is_float:
                return self.builder.fcmp_ordered('<', left, right, name="lttmp")
            return self.builder.icmp_signed('<', left, right, name="lttmp")

        elif expr.op == '>':
            if is_float:
                return self.builder.fcmp_ordered('>', left, right, name="gttmp")
            return self.builder.icmp_signed('>', left, right, name="gttmp")

        elif expr.op == '<=':
            if is_float:
                return self.builder.fcmp_ordered('<=', left, right, name="letmp")
            return self.builder.icmp_signed('<=', left, right, name="letmp")

        elif expr.op == '>=':
            if is_float:
                return self.builder.fcmp_ordered('>=', left, right, name="getmp")
            return self.builder.icmp_signed('>=', left, right, name="getmp")

        else:
            raise ValueError(f"Unknown binary operator: {expr.op}")

    def _generate_logical_and(self, expr: BinaryOp):
        """Generate short-circuit && evaluation.

        left && right:
        - Evaluate left
        - If left is false, result is false (don't evaluate right)
        - If left is true, result is value of right
        """
        func = self.builder.block.function

        # Create blocks
        eval_right_block = func.append_basic_block(name="and_right")
        merge_block = func.append_basic_block(name="and_merge")

        # Evaluate left operand
        left = self._generate_expression(expr.left)
        left_block = self.builder.block

        # Branch: if left is false, go to merge with false; else evaluate right
        self.builder.cbranch(left, eval_right_block, merge_block)

        # Evaluate right operand
        self.builder.position_at_end(eval_right_block)
        right = self._generate_expression(expr.right)
        right_block = self.builder.block
        self.builder.branch(merge_block)

        # Merge: phi node selects result
        self.builder.position_at_end(merge_block)
        phi = self.builder.phi(ir.IntType(1), name="and_result")
        phi.add_incoming(ir.Constant(ir.IntType(1), 0), left_block)  # false from left
        phi.add_incoming(right, right_block)  # right value if left was true

        return phi

    def _generate_logical_or(self, expr: BinaryOp):
        """Generate short-circuit || evaluation.

        left || right:
        - Evaluate left
        - If left is true, result is true (don't evaluate right)
        - If left is false, result is value of right
        """
        func = self.builder.block.function

        # Create blocks
        eval_right_block = func.append_basic_block(name="or_right")
        merge_block = func.append_basic_block(name="or_merge")

        # Evaluate left operand
        left = self._generate_expression(expr.left)
        left_block = self.builder.block

        # Branch: if left is true, go to merge with true; else evaluate right
        self.builder.cbranch(left, merge_block, eval_right_block)

        # Evaluate right operand
        self.builder.position_at_end(eval_right_block)
        right = self._generate_expression(expr.right)
        right_block = self.builder.block
        self.builder.branch(merge_block)

        # Merge: phi node selects result
        self.builder.position_at_end(merge_block)
        phi = self.builder.phi(ir.IntType(1), name="or_result")
        phi.add_incoming(ir.Constant(ir.IntType(1), 1), left_block)  # true from left
        phi.add_incoming(right, right_block)  # right value if left was false

        return phi

    def _generate_unary_op(self, expr: UnaryOp):
        operand = self._generate_expression(expr.operand)

        if expr.op == '-':
            if isinstance(operand.type, ir.DoubleType):
                return self.builder.fneg(operand, name="negtmp")
            zero = ir.Constant(ir.IntType(64), 0)
            return self.builder.sub(zero, operand, name="negtmp")

        elif expr.op == 'not':
            # Logical NOT: flip the boolean (XOR with 1)
            return self.builder.xor(operand, ir.Constant(ir.IntType(1), 1), name="nottmp")

        else:
            raise ValueError(f"Unknown unary operator: {expr.op}")

    def _generate_move_expr(self, expr: MoveExpr):
        """Generate code for move expression - transfers ownership without copying."""
        var_name = expr.variable
        if var_name not in self.variables:
            raise ValueError(f"Undefined variable: {var_name}")

        # Load the value
        value = self.builder.load(self.variables[var_name], name=f"{var_name}_moved")

        # Mark as moved - skip deinit and prevent further use
        self.moved_variables.add(var_name)

        return value

    def _generate_cast_expr(self, expr: CastExpr):
        """Generate code for type cast: expr as Type"""
        value = self._generate_expression(expr.expr)
        from_saw_type = self._infer_saw_type(expr.expr)
        to_type = expr.target_type
        to_llvm = self._get_llvm_type(to_type)

        # Get actual LLVM bit widths from the values (more reliable than Saw types
        # because integer literals are always i64 in LLVM)
        if isinstance(value.type, ir.IntType) and isinstance(to_llvm, ir.IntType):
            from_bits = value.type.width
            to_bits = to_llvm.width

            # Determine signedness from Saw type
            signed_kinds = {TypeKind.INT, TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64}
            from_signed = from_saw_type and from_saw_type.kind in signed_kinds

            if to_bits > from_bits:
                # Widening - use sign extension or zero extension based on source signedness
                if from_signed:
                    return self.builder.sext(value, to_llvm, name="sext")
                else:
                    return self.builder.zext(value, to_llvm, name="zext")
            elif to_bits < from_bits:
                # Narrowing - truncate
                return self.builder.trunc(value, to_llvm, name="trunc")
            else:
                # Same size - no conversion needed
                return value

        # Pointer to pointer conversion
        if isinstance(value.type, ir.PointerType) and isinstance(to_llvm, ir.PointerType):
            return self.builder.bitcast(value, to_llvm, name="ptrcast")

        raise ValueError(f"Cannot cast from {value.type} to {to_llvm}")

    def _generate_function_call(self, expr: FunctionCall):
        # Handle built-in print function
        if expr.name == "print":
            return self._generate_print(expr.arguments)

        # Handle built-in sizeof<T>() function
        if expr.name == "sizeof":
            return self._generate_sizeof(expr)

        # Check if the name refers to a closure variable
        if expr.name in self.variables:
            closure_ptr = self.variables[expr.name]
            closure_val = self.builder.load(closure_ptr, name="closure")
            # Check if it's a closure struct (has fn_ptr and env_ptr fields)
            if isinstance(closure_val.type, ir.LiteralStructType) and len(closure_val.type.elements) == 2:
                # Call the closure
                fn_ptr = self.builder.extract_value(closure_val, 0, name="fn_ptr")
                env_ptr = self.builder.extract_value(closure_val, 1, name="env_ptr")
                arg_vals = [self._generate_expression(arg.value) for arg in expr.arguments]
                return self.builder.call(fn_ptr, [env_ptr] + arg_vals, name="closure_call")

        # Check if this is actually a struct init (parser treats empty parens as function call)
        if expr.name in self.generic_structs or expr.name in self.struct_types:
            # Convert to struct init and generate that instead
            field_inits = [(arg.name, arg.value) for arg in expr.arguments if arg.name]
            struct_init = StructInit(
                struct_name=expr.name,
                field_inits=field_inits,
                type_args=expr.type_args,
                line=expr.line,
                column=expr.column
            )
            # Copy resolved_init_params if it was set during typechecking
            if hasattr(expr, 'resolved_init_params'):
                struct_init.resolved_init_params = expr.resolved_init_params
            return self._generate_struct_init(struct_init)

        # Check if this is a call to a generic function
        if expr.name in self.generic_functions:
            if not expr.type_args:
                raise ValueError(
                    f"Generic function {expr.name} requires type arguments. "
                    f"Use {expr.name}<Type>(...)"
                )
            # Instantiate the generic function
            mangled_name = self._instantiate_generic_function(expr.name, expr.type_args)
            func = self.functions[mangled_name]
        else:
            # Look up regular user-defined function
            if expr.name not in self.functions:
                raise ValueError(f"Undefined function: {expr.name}")
            func = self.functions[expr.name]

        # Arguments are now Argument objects with .value
        args = [self._generate_expression(arg.value) for arg in expr.arguments]
        result = self.builder.call(func, args, name="calltmp")

        # Wrap result in optional for extern functions that return nullable pointers
        if expr.name in self.extern_optional_returns:
            inner_type = self.extern_optional_returns[expr.name]
            optional_type = self._get_llvm_type(SawType(TypeKind.OPTIONAL, inner_type=inner_type))
            # Check if pointer is NULL
            null_ptr = ir.Constant(result.type, None)
            is_not_null = self.builder.icmp_unsigned('!=', result, null_ptr, name="is_not_null")
            # Build optional struct: {i1 is_some, T value}
            opt_val = ir.Constant(optional_type, ir.Undefined)
            opt_val = self.builder.insert_value(opt_val, is_not_null, 0, name="opt_flag")
            opt_val = self.builder.insert_value(opt_val, result, 1, name="opt_val")
            return opt_val

        return result

    def _generate_print(self, arguments: List[Argument]):
        if not arguments:
            # Print newline
            fmt = self._create_string_constant("\n")
            zero = ir.Constant(ir.IntType(32), 0)
            fmt_ptr = self.builder.gep(fmt, [zero, zero], inbounds=True)
            return self.builder.call(self.printf, [fmt_ptr])

        # Arguments are Argument objects with .value
        arg = arguments[0]
        value = self._generate_expression(arg.value)

        # Choose format based on type
        if isinstance(value.type, ir.IntType):
            if value.type.width == 1:
                # Bool - convert to string
                fmt = self._create_string_constant("%s\n")
                zero = ir.Constant(ir.IntType(32), 0)
                fmt_ptr = self.builder.gep(fmt, [zero, zero], inbounds=True)

                # Create true/false strings
                true_str = self._create_string_constant("true")
                false_str = self._create_string_constant("false")
                true_ptr = self.builder.gep(true_str, [zero, zero], inbounds=True)
                false_ptr = self.builder.gep(false_str, [zero, zero], inbounds=True)

                str_ptr = self.builder.select(value, true_ptr, false_ptr)
                return self.builder.call(self.printf, [fmt_ptr, str_ptr])
            else:
                # Integer - extend to i64 for printf %lld format
                fmt = self._create_string_constant("%lld\n")
                zero = ir.Constant(ir.IntType(32), 0)
                fmt_ptr = self.builder.gep(fmt, [zero, zero], inbounds=True)
                # Extend smaller integers to i64 for printf
                if value.type.width < 64:
                    # Use zext for unsigned types, sext for signed types
                    saw_type = self._infer_saw_type(arg.value)
                    unsigned_kinds = {TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64}
                    if saw_type and saw_type.kind in unsigned_kinds:
                        value = self.builder.zext(value, ir.IntType(64), name="print_ext")
                    else:
                        value = self.builder.sext(value, ir.IntType(64), name="print_ext")
                return self.builder.call(self.printf, [fmt_ptr, value])

        elif isinstance(value.type, ir.DoubleType):
            fmt = self._create_string_constant("%f\n")
            zero = ir.Constant(ir.IntType(32), 0)
            fmt_ptr = self.builder.gep(fmt, [zero, zero], inbounds=True)
            return self.builder.call(self.printf, [fmt_ptr, value])

        elif isinstance(value.type, ir.PointerType):
            # String
            fmt = self._create_string_constant("%s\n")
            zero = ir.Constant(ir.IntType(32), 0)
            fmt_ptr = self.builder.gep(fmt, [zero, zero], inbounds=True)
            return self.builder.call(self.printf, [fmt_ptr, value])

        else:
            raise ValueError(f"Cannot print type: {value.type}")

    def _generate_sizeof(self, expr: FunctionCall):
        """Generate code for sizeof<T>() - returns the size in bytes of type T."""
        # Get the type argument
        if not expr.type_args or len(expr.type_args) != 1:
            raise ValueError("sizeof requires exactly one type argument")

        saw_type = expr.type_args[0]
        # Resolve type parameters if in a generic context
        if saw_type.kind == TypeKind.STRUCT and saw_type.struct_name in self.type_param_context:
            saw_type = self.type_param_context[saw_type.struct_name]
        llvm_type = self._get_llvm_type(saw_type)
        size = llvm_type.get_abi_size(self.target_data)
        return ir.Constant(ir.IntType(64), size)

    def _generate_if_expression(self, expr: IfExpr):
        cond = self._generate_expression(expr.condition)

        # Convert to i1 if needed
        if isinstance(cond.type, ir.IntType) and cond.type.width != 1:
            zero = ir.Constant(cond.type, 0)
            cond = self.builder.icmp_signed('!=', cond, zero, name="ifcond")

        func = self.builder.function
        then_bb = func.append_basic_block(name="then")
        else_bb = func.append_basic_block(name="else")
        merge_bb = func.append_basic_block(name="ifcont")

        self.builder.cbranch(cond, then_bb, else_bb)

        # Generate then branch
        self.builder.position_at_start(then_bb)
        then_val = self._generate_block(expr.then_branch)
        then_bb_end = self.builder.block  # May have changed due to nested control flow
        then_terminated = self.builder.block.is_terminated

        # Generate else branch
        self.builder.position_at_start(else_bb)
        if expr.else_branch:
            else_val = self._generate_block(expr.else_branch)
        else:
            else_val = None
        else_bb_end = self.builder.block
        else_terminated = self.builder.block.is_terminated

        # If we don't need the result (statement context), skip result-capturing logic
        need_result = getattr(self, '_need_result', True)
        if not need_result:
            # Just add branches without capturing result values
            if not then_terminated:
                self.builder.position_at_end(then_bb_end)
                self.builder.branch(merge_bb)
            if not else_terminated:
                self.builder.position_at_end(else_bb_end)
                self.builder.branch(merge_bb)
            self.builder.position_at_start(merge_bb)
            return None

        # Determine result type and wrap values if needed
        result_alloca = None
        if then_val is not None and else_val is not None:
            if then_val.type != else_val.type:
                # Check if we need to wrap one in Optional
                then_is_optional = (isinstance(then_val.type, ir.LiteralStructType) and
                                   len(then_val.type.elements) == 2 and
                                   isinstance(then_val.type.elements[0], ir.IntType) and
                                   then_val.type.elements[0].width == 1)
                else_is_optional = (isinstance(else_val.type, ir.LiteralStructType) and
                                   len(else_val.type.elements) == 2 and
                                   isinstance(else_val.type.elements[0], ir.IntType) and
                                   else_val.type.elements[0].width == 1)

                if else_is_optional and then_val.type == else_val.type.elements[1]:
                    # else is Optional, then is inner type - wrap then
                    optional_type = else_val.type

                    # Create alloca for result before branches
                    self.builder.position_at_start(func.entry_basic_block)
                    result_alloca = self.builder.alloca(optional_type, name="if_result")
                    self.builder.position_at_end(func.entry_basic_block)

                    # Go back to then block and wrap + store
                    self.builder.position_at_end(then_bb_end)
                    if not then_terminated:
                        wrapped_then = ir.Constant(optional_type, ir.Undefined)
                        wrapped_then = self.builder.insert_value(wrapped_then, ir.Constant(ir.IntType(1), 1), 0)
                        wrapped_then = self.builder.insert_value(wrapped_then, then_val, 1, name="some_then")
                        self.builder.store(wrapped_then, result_alloca)
                        self.builder.branch(merge_bb)

                    # Go to else block and store
                    self.builder.position_at_end(else_bb_end)
                    if not else_terminated:
                        self.builder.store(else_val, result_alloca)
                        self.builder.branch(merge_bb)

                    # Load result at merge
                    self.builder.position_at_start(merge_bb)
                    return self.builder.load(result_alloca, name="iftmp")

                elif then_is_optional and else_val.type == then_val.type.elements[1]:
                    # then is Optional, else is inner type - wrap else
                    optional_type = then_val.type

                    # Create alloca for result
                    self.builder.position_at_start(func.entry_basic_block)
                    result_alloca = self.builder.alloca(optional_type, name="if_result")
                    self.builder.position_at_end(func.entry_basic_block)

                    # Go to then block and store
                    self.builder.position_at_end(then_bb_end)
                    if not then_terminated:
                        self.builder.store(then_val, result_alloca)
                        self.builder.branch(merge_bb)

                    # Go to else block and wrap + store
                    self.builder.position_at_end(else_bb_end)
                    if not else_terminated:
                        wrapped_else = ir.Constant(optional_type, ir.Undefined)
                        wrapped_else = self.builder.insert_value(wrapped_else, ir.Constant(ir.IntType(1), 1), 0)
                        wrapped_else = self.builder.insert_value(wrapped_else, else_val, 1, name="some_else")
                        self.builder.store(wrapped_else, result_alloca)
                        self.builder.branch(merge_bb)

                    # Load result at merge
                    self.builder.position_at_start(merge_bb)
                    return self.builder.load(result_alloca, name="iftmp")

        # Normal case - add branches if not terminated
        if not then_terminated:
            self.builder.position_at_end(then_bb_end)
            self.builder.branch(merge_bb)
        if not else_terminated:
            self.builder.position_at_end(else_bb_end)
            self.builder.branch(merge_bb)

        # Merge block
        self.builder.position_at_start(merge_bb)

        # If both branches produce values of the same type, create a phi node
        if then_val is not None and else_val is not None:
            if then_val.type == else_val.type:
                phi = self.builder.phi(then_val.type, name="iftmp")
                phi.add_incoming(then_val, then_bb_end)
                phi.add_incoming(else_val, else_bb_end)
                return phi

        return then_val

    def _generate_if_let_expression(self, expr: IfLetExpr):
        """Generate code for if let/var optional binding."""
        # Generate the optional expression
        optional_val = self._generate_expression(expr.optional_expr)

        # Extract the is_some flag
        is_some = self.builder.extract_value(optional_val, 0, name="is_some")

        func = self.builder.function
        then_bb = func.append_basic_block(name="if_let_then")
        else_bb = func.append_basic_block(name="if_let_else")
        merge_bb = func.append_basic_block(name="if_let_merge")

        self.builder.cbranch(is_some, then_bb, else_bb)

        # Generate then branch - with bound variable
        self.builder.position_at_start(then_bb)

        # Extract the inner value from the optional
        inner_val = self.builder.extract_value(optional_val, 1, name="unwrapped")

        # For 'if let', create a copy; for 'if var', we store and use reference
        # Currently, we always create a local variable (copy semantics for if let)
        # For if var reference semantics, we'd need to track the original optional's alloca
        alloca = self.builder.alloca(inner_val.type, name=expr.name)
        self.builder.store(inner_val, alloca)
        self.variables[expr.name] = alloca

        # Store the type of the bound variable for type inference
        # Infer the inner type from the optional expression
        opt_type = self._infer_saw_type(expr.optional_expr)
        if opt_type and opt_type.kind == TypeKind.OPTIONAL and opt_type.inner_type:
            self.variable_types[expr.name] = opt_type.inner_type

        then_val = self._generate_block(expr.then_branch)

        # Remove the bound variable from scope after the block
        del self.variables[expr.name]
        if expr.name in self.variable_types:
            del self.variable_types[expr.name]

        # Capture state before adding terminator
        then_terminated = self.builder.block.is_terminated
        then_bb_end = self.builder.block

        # Generate else branch
        self.builder.position_at_start(else_bb)
        if expr.else_branch:
            else_val = self._generate_block(expr.else_branch)
        else:
            else_val = None
        else_terminated = self.builder.block.is_terminated
        else_bb_end = self.builder.block

        # Helper to check if a type is an optional struct
        def is_optional_struct(t):
            return (isinstance(t, ir.LiteralStructType) and
                    len(t.elements) == 2 and
                    t.elements[0] == ir.IntType(1))

        # If we don't need the result (statement context), skip result-capturing logic
        need_result = getattr(self, '_need_result', True)
        if not need_result:
            # Just add branches without capturing result values
            if not then_terminated:
                self.builder.position_at_end(then_bb_end)
                self.builder.branch(merge_bb)
            if not else_terminated:
                self.builder.position_at_end(else_bb_end)
                self.builder.branch(merge_bb)
            self.builder.position_at_start(merge_bb)
            return None

        # Handle type mismatch (optional wrapping needed)
        if then_val is not None and else_val is not None and then_val.type != else_val.type:
            then_is_optional = is_optional_struct(then_val.type)
            else_is_optional = is_optional_struct(else_val.type)

            if else_is_optional and then_val.type == else_val.type.elements[1]:
                # then is T, else is T? - wrap then in Some
                optional_type = else_val.type

                # Create alloca for result at entry
                self.builder.position_at_start(func.entry_basic_block)
                result_alloca = self.builder.alloca(optional_type, name="if_let_result")
                self.builder.position_at_end(func.entry_basic_block)

                # Wrap then value and store
                self.builder.position_at_end(then_bb_end)
                if not then_terminated:
                    wrapped_then = ir.Constant(optional_type, ir.Undefined)
                    wrapped_then = self.builder.insert_value(wrapped_then, ir.Constant(ir.IntType(1), 1), 0)
                    wrapped_then = self.builder.insert_value(wrapped_then, then_val, 1, name="some_then")
                    self.builder.store(wrapped_then, result_alloca)
                    self.builder.branch(merge_bb)

                # Store else value directly
                self.builder.position_at_end(else_bb_end)
                if not else_terminated:
                    self.builder.store(else_val, result_alloca)
                    self.builder.branch(merge_bb)

                # Load result at merge
                self.builder.position_at_start(merge_bb)
                return self.builder.load(result_alloca, name="if_let_tmp")

            elif then_is_optional and else_val.type == then_val.type.elements[1]:
                # then is T?, else is T - wrap else in Some
                optional_type = then_val.type

                # Create alloca for result at entry
                self.builder.position_at_start(func.entry_basic_block)
                result_alloca = self.builder.alloca(optional_type, name="if_let_result")
                self.builder.position_at_end(func.entry_basic_block)

                # Store then value directly
                self.builder.position_at_end(then_bb_end)
                if not then_terminated:
                    self.builder.store(then_val, result_alloca)
                    self.builder.branch(merge_bb)

                # Wrap else value and store
                self.builder.position_at_end(else_bb_end)
                if not else_terminated:
                    wrapped_else = ir.Constant(optional_type, ir.Undefined)
                    wrapped_else = self.builder.insert_value(wrapped_else, ir.Constant(ir.IntType(1), 1), 0)
                    wrapped_else = self.builder.insert_value(wrapped_else, else_val, 1, name="some_else")
                    self.builder.store(wrapped_else, result_alloca)
                    self.builder.branch(merge_bb)

                # Load result at merge
                self.builder.position_at_start(merge_bb)
                return self.builder.load(result_alloca, name="if_let_tmp")

        # Use alloca-based storage for if-let result values when we have values
        # (avoids phi node dominance issues with nested if-let expressions)
        # The value from nested control flow might not dominate the merge block

        if then_val is not None and else_val is not None and then_val.type == else_val.type:
            # Both branches produce values of the same type
            # Create alloca for result at function entry
            self.builder.position_at_start(func.entry_basic_block)
            result_alloca = self.builder.alloca(then_val.type, name="if_let_result")

            # Store then value at end of then branch
            self.builder.position_at_end(then_bb_end)
            if not then_terminated:
                self.builder.store(then_val, result_alloca)
                self.builder.branch(merge_bb)

            # Store else value at end of else branch
            self.builder.position_at_end(else_bb_end)
            if not else_terminated:
                self.builder.store(else_val, result_alloca)
                self.builder.branch(merge_bb)

            # Load result at merge
            self.builder.position_at_start(merge_bb)
            return self.builder.load(result_alloca, name="if_let_tmp")

        elif then_val is not None and else_val is None and not isinstance(then_val.type, ir.VoidType):
            # Only then branch produces a non-void value - use alloca to ensure dominance
            # Create alloca for result at function entry and initialize to zero
            self.builder.position_at_start(func.entry_basic_block)
            result_alloca = self.builder.alloca(then_val.type, name="if_let_result")
            # Initialize to zero/null in case else path is taken
            zero_val = ir.Constant(then_val.type, 0 if isinstance(then_val.type, ir.IntType) else None)
            self.builder.store(zero_val, result_alloca)

            # Store then value at end of then branch
            self.builder.position_at_end(then_bb_end)
            if not then_terminated:
                self.builder.store(then_val, result_alloca)
                self.builder.branch(merge_bb)

            # Else branch doesn't produce a value, just branch to merge
            self.builder.position_at_end(else_bb_end)
            if not else_terminated:
                self.builder.branch(merge_bb)

            # Load result at merge
            self.builder.position_at_start(merge_bb)
            return self.builder.load(result_alloca, name="if_let_tmp")

        else:
            # Normal case - add branches if not terminated
            if not then_terminated:
                self.builder.position_at_end(then_bb_end)
                self.builder.branch(merge_bb)
            if not else_terminated:
                self.builder.position_at_end(else_bb_end)
                self.builder.branch(merge_bb)

            # Merge block
            self.builder.position_at_start(merge_bb)

            return then_val

    def _generate_guard_let_statement(self, stmt: GuardLetStatement):
        """Generate code for guard let/var optional binding."""
        # Generate the optional expression
        optional_val = self._generate_expression(stmt.optional_expr)

        # Extract the is_some flag
        is_some = self.builder.extract_value(optional_val, 0, name="guard_is_some")

        func = self.builder.function
        else_bb = func.append_basic_block(name="guard_else")
        continue_bb = func.append_basic_block(name="guard_continue")

        # If Some, continue; if None, go to else block
        self.builder.cbranch(is_some, continue_bb, else_bb)

        # Generate else branch (early exit)
        self.builder.position_at_start(else_bb)
        self._generate_block(stmt.else_branch)
        # Note: else_branch must contain a return/break/etc, so no need to branch

        # If else branch is not terminated, add unreachable (shouldn't happen with proper guard)
        if not self.builder.block.is_terminated:
            self.builder.unreachable()

        # Continue block - extract value and bind variable
        self.builder.position_at_start(continue_bb)

        # Extract the inner value from the optional
        inner_val = self.builder.extract_value(optional_val, 1, name="guard_unwrapped")

        # Store in a local variable
        alloca = self.builder.alloca(inner_val.type, name=stmt.name)
        self.builder.store(inner_val, alloca)
        self.variables[stmt.name] = alloca

        # Store the type of the bound variable for type inference
        opt_type = self._infer_saw_type(stmt.optional_expr)
        if opt_type and opt_type.kind == TypeKind.OPTIONAL and opt_type.inner_type:
            self.variable_types[stmt.name] = opt_type.inner_type

    def _generate_tuple_literal(self, expr: TupleLiteral):
        """Generate code for a tuple literal."""
        # Generate each element
        element_values = [self._generate_expression(elem) for elem in expr.elements]

        # Create the tuple type
        element_types = [val.type for val in element_values]
        tuple_type = ir.LiteralStructType(element_types)

        # Build the tuple value
        tuple_val = ir.Constant(tuple_type, ir.Undefined)
        for i, elem_val in enumerate(element_values):
            tuple_val = self.builder.insert_value(tuple_val, elem_val, i)

        return tuple_val

    def _generate_tuple_index(self, expr: TupleIndex):
        """Generate code for tuple indexing."""
        tuple_val = self._generate_expression(expr.tuple_expr)

        # Extract the element at the given index
        return self.builder.extract_value(tuple_val, expr.index)

    def _generate_array_literal(self, expr: ArrayLiteral):
        """Generate code for array literal."""
        if len(expr.elements) == 0:
            raise ValueError("Empty array literals not supported")

        # Generate all element values
        element_values = [self._generate_expression(elem) for elem in expr.elements]

        # Get the element type from the first element
        elem_type = element_values[0].type
        array_type = ir.ArrayType(elem_type, len(element_values))

        # Build the array value by inserting elements
        array_val = ir.Constant(array_type, ir.Undefined)
        for i, val in enumerate(element_values):
            array_val = self.builder.insert_value(array_val, val, i, name=f"arr_{i}")

        return array_val

    def _generate_array_index(self, expr: ArrayIndex):
        """Generate code for array or tuple indexing with [index] syntax."""
        container_val = self._generate_expression(expr.array_expr)

        # Check if it's a tuple (struct type in LLVM) or array
        if isinstance(container_val.type, ir.ArrayType):
            # Array indexing - need to allocate, store, and use GEP
            index_val = self._generate_expression(expr.index)

            # Allocate space for the array on stack
            array_ptr = self.builder.alloca(container_val.type, name="arr_tmp")
            self.builder.store(container_val, array_ptr)

            # Use GEP to get pointer to element
            zero = ir.Constant(ir.IntType(64), 0)
            elem_ptr = self.builder.gep(array_ptr, [zero, index_val], name="elem_ptr")

            # Load the element
            return self.builder.load(elem_ptr, name="elem")

        elif isinstance(container_val.type, ir.LiteralStructType):
            # Tuple indexing - index must be a constant (checked by typechecker)
            if isinstance(expr.index, IntLiteral):
                index = expr.index.value
                return self.builder.extract_value(container_val, index, name="tuple_elem")
            else:
                raise ValueError("Tuple index must be a compile-time constant")

        elif isinstance(container_val.type, ir.PointerType):
            # Pointer indexing: ptr[i] - use GEP to offset and load
            index_val = self._generate_expression(expr.index)
            elem_ptr = self.builder.gep(container_val, [index_val], name="ptr_idx")
            return self.builder.load(elem_ptr, name="ptr_elem")

        else:
            raise ValueError(f"Cannot index into type: {container_val.type}")

    def _generate_struct_init(self, expr: StructInit):
        """Generate code for struct initialization."""
        # Handle generic struct instantiation
        struct_name = expr.struct_name
        if expr.type_args:
            # Substitute type parameters in type args if we're in a generic context
            # e.g., Vector<T>(...) inside Vector<Int>.init() should become Vector<Int>(...)
            resolved_type_args = []
            for type_arg in expr.type_args:
                if self.type_param_context:
                    resolved = type_arg.substitute(self.type_param_context)
                    resolved_type_args.append(resolved)
                else:
                    resolved_type_args.append(type_arg)
            # This is a generic struct - ensure monomorphized version exists
            struct_name = self._ensure_monomorphized_struct(expr.struct_name, resolved_type_args)

        if struct_name not in self.struct_types:
            raise ValueError(f"Undefined struct: {struct_name}")

        # Check if this is a custom init method call
        if expr.resolved_init_params is not None:
            # Custom init - call the init method
            mangled_name = self._mangle_method_name(struct_name, "init", expr.resolved_init_params)
            init_func = self.functions[mangled_name]

            # Generate arguments in the order expected by the init method
            args = []
            param_to_value = {param_name: value for param_name, value in expr.field_inits}
            for param_name in expr.resolved_init_params:
                arg_value = self._generate_expression(param_to_value[param_name])
                args.append(arg_value)

            # Call the init method
            return self.builder.call(init_func, args)

        # Field initialization (original behavior)
        llvm_struct_type, field_order = self.struct_types[struct_name]

        # Get field types for CustomCopy handling (use namespace)
        field_types = self.namespace.get_struct_fields(struct_name) or {}

        # Create a map from field name to value, handling CustomCopy
        field_values = {}
        for field_name, value_expr in expr.field_inits:
            value = self._generate_expression(value_expr)

            # Check if this field needs copy() called
            field_type = field_types.get(field_name)
            if field_type and self._needs_copy_for_struct_init(value_expr, field_type):
                value = self._generate_copy(value, field_type)

            field_values[field_name] = value

        # Build the struct value in the correct field order
        struct_val = ir.Constant(llvm_struct_type, ir.Undefined)
        for i, field_name in enumerate(field_order):
            if field_name in field_values:
                val = field_values[field_name]
                # Check if we need to wrap in optional (non-optional value for optional field)
                expected_field_type = llvm_struct_type.elements[i]
                if isinstance(expected_field_type, ir.LiteralStructType) and len(expected_field_type.elements) == 2:
                    # Expected is optional {i1, T}, check if value needs wrapping
                    if not isinstance(val.type, ir.LiteralStructType):
                        # Value is not optional, wrap it
                        val = self._wrap_in_optional(val)
                struct_val = self.builder.insert_value(struct_val, val, i)

        return struct_val

    def _generate_member_access(self, expr: MemberAccess):
        """Generate code for member access on structs or enum variant access."""
        # Special case: EnumName.VariantName (simple variant with no associated values)
        # Check both concrete enums and generic enums
        if isinstance(expr.object, Identifier):
            is_enum = expr.object.name in self.enum_types
            is_generic_enum = expr.object.name in self.generic_enums
            if is_enum or is_generic_enum:
                # This is an enum variant access - convert to EnumInit
                enum_init = EnumInit(
                    enum_name=expr.object.name,
                    variant_name=expr.member,
                    arguments=[],
                    type_args=expr.object.type_args,  # Pass type_args for generic enums
                    line=expr.line,
                    column=expr.column
                )
                return self._generate_enum_init(enum_init)

        obj_val = self._generate_expression(expr.object)

        # Determine the struct type
        # For now, we need to infer the struct type from the object expression
        # This is a bit hacky, but works for simple cases
        # In a more sophisticated system, we'd track type info through the codegen

        # For now, assume the object is a struct and find which one based on its LLVM type
        obj_type = obj_val.type

        # Handle pointer to struct (e.g., var self methods)
        is_pointer = isinstance(obj_type, ir.PointerType)
        if is_pointer:
            # Load the struct value from the pointer
            obj_val = self.builder.load(obj_val, name="deref")
            obj_type = obj_val.type

        # For identified types, get name directly
        struct_name = None
        if hasattr(obj_type, 'name') and obj_type.name in self.struct_types:
            struct_name = obj_type.name
        else:
            # Fallback to string comparison for literal types
            for name, (llvm_type, _) in self.struct_types.items():
                if str(obj_type) == str(llvm_type):
                    struct_name = name
                    break

        if struct_name and struct_name in self.struct_types:
            _, field_order = self.struct_types[struct_name]
            if expr.member in field_order:
                field_index = field_order.index(expr.member)
                result = self.builder.extract_value(obj_val, field_index)
                return result

        # Debug: print available struct types
        for name, (llvm_type, fields) in self.struct_types.items():
            print(f"  {name}: {llvm_type} -> {fields}")
        raise ValueError(f"Cannot find field {expr.member} in struct with type {obj_type}")

    def _wrap_in_optional(self, value):
        """Wrap a value in an optional type (for implicit wrapping)."""
        optional_type = ir.LiteralStructType([ir.IntType(1), value.type])
        optional_val = ir.Constant(optional_type, ir.Undefined)

        # Set is_some to true
        true_val = ir.Constant(ir.IntType(1), 1)
        optional_val = self.builder.insert_value(optional_val, true_val, 0)

        # Set the value
        optional_val = self.builder.insert_value(optional_val, value, 1)

        return optional_val

    def _is_optional_type(self, llvm_type) -> bool:
        """Check if an LLVM type is an optional (struct with i1 flag and value)."""
        return (isinstance(llvm_type, ir.LiteralStructType) and
                len(llvm_type.elements) == 2 and
                llvm_type.elements[0] == ir.IntType(1))

    def _generate_none_literal(self, expr: NoneLiteral):
        """Generate code for None literal."""
        # Create an optional with is_some = false
        # Priority: 1) resolved_type from typechecker, 2) current_return_type, 3) default i64
        inner_llvm_type = None

        if expr.resolved_type and expr.resolved_type.inner_type:
            # Use type from typechecker annotation
            inner_type = expr.resolved_type.inner_type
            if self.type_param_context:
                inner_type = inner_type.substitute(self.type_param_context)
            inner_llvm_type = self._get_llvm_type(inner_type)
        elif self.current_return_type and self.current_return_type.is_optional():
            # Fallback: use current function/method return type
            inner_type = self.current_return_type.inner_type
            if inner_type and self.type_param_context:
                inner_type = inner_type.substitute(self.type_param_context)
            if inner_type:
                inner_llvm_type = self._get_llvm_type(inner_type)

        if inner_llvm_type is None:
            # No fallback - fail loudly so we can fix the root cause
            raise ValueError(
                f"None literal at line {expr.line} has no type information. "
                f"resolved_type={expr.resolved_type}, "
                f"current_return_type={self.current_return_type}"
            )

        optional_type = ir.LiteralStructType([ir.IntType(1), inner_llvm_type])
        optional_val = ir.Constant(optional_type, ir.Undefined)

        # Set is_some to false
        false_val = ir.Constant(ir.IntType(1), 0)
        optional_val = self.builder.insert_value(optional_val, false_val, 0)

        return optional_val

    def _generate_force_unwrap(self, expr: ForceUnwrap):
        """Generate code for force unwrap (expr!)."""
        optional_val = self._generate_expression(expr.expr)

        # Extract the is_some flag
        is_some = self.builder.extract_value(optional_val, 0, name="is_some")

        # Runtime check: panic if None
        func = self.builder.function
        unwrap_ok_bb = func.append_basic_block(name="unwrap.ok")
        unwrap_panic_bb = func.append_basic_block(name="unwrap.panic")

        self.builder.cbranch(is_some, unwrap_ok_bb, unwrap_panic_bb)

        # Panic block: print error and abort
        self.builder.position_at_end(unwrap_panic_bb)
        panic_msg = f"panic: force unwrap of None at line {expr.line}\n\0"
        panic_str = ir.Constant(ir.ArrayType(ir.IntType(8), len(panic_msg)),
                                bytearray(panic_msg.encode('utf-8')))
        panic_global = ir.GlobalVariable(self.module, panic_str.type, name=f".panic_msg.{id(expr)}")
        panic_global.global_constant = True
        panic_global.initializer = panic_str
        panic_global.linkage = 'private'
        panic_ptr = self.builder.bitcast(panic_global, ir.PointerType(ir.IntType(8)))
        self.builder.call(self.printf, [panic_ptr])
        self.builder.call(self.abort, [])
        self.builder.unreachable()

        # OK block: extract and return the value
        self.builder.position_at_end(unwrap_ok_bb)
        return self.builder.extract_value(optional_val, 1, name="unwrapped")

    def _generate_nil_coalesce(self, expr: NilCoalesce):
        """Generate code for nil coalescing (expr ?? default)."""
        optional_val = self._generate_expression(expr.expr)

        # Extract the is_some flag
        is_some = self.builder.extract_value(optional_val, 0, name="is_some")

        # Create blocks for the conditional
        func = self.builder.function
        some_bb = func.append_basic_block(name="some")
        none_bb = func.append_basic_block(name="none")
        merge_bb = func.append_basic_block(name="coalesce_merge")

        self.builder.cbranch(is_some, some_bb, none_bb)

        # Some branch - extract the value
        self.builder.position_at_start(some_bb)
        some_val = self.builder.extract_value(optional_val, 1, name="some_value")
        self.builder.branch(merge_bb)
        some_bb = self.builder.block

        # None branch - evaluate default
        self.builder.position_at_start(none_bb)
        none_val = self._generate_expression(expr.default)
        self.builder.branch(merge_bb)
        none_bb = self.builder.block

        # Merge
        self.builder.position_at_start(merge_bb)
        phi = self.builder.phi(some_val.type, name="coalesced")
        phi.add_incoming(some_val, some_bb)
        phi.add_incoming(none_val, none_bb)

        return phi

    def _generate_optional_chain(self, expr: OptionalChain):
        """Generate code for optional chaining (expr?.member)."""
        optional_val = self._generate_expression(expr.expr)

        # Extract the is_some flag
        is_some = self.builder.extract_value(optional_val, 0, name="is_some")

        # Create blocks
        func = self.builder.function
        some_bb = func.append_basic_block(name="chain_some")
        none_bb = func.append_basic_block(name="chain_none")
        merge_bb = func.append_basic_block(name="chain_merge")

        self.builder.cbranch(is_some, some_bb, none_bb)

        # Some branch - unwrap and access member
        self.builder.position_at_start(some_bb)
        unwrapped = self.builder.extract_value(optional_val, 1, name="unwrapped")

        # Access the member (assuming struct)
        # Find the struct type and field index
        unwrapped_type = unwrapped.type
        struct_name = None
        if hasattr(unwrapped_type, 'name') and unwrapped_type.name in self.struct_types:
            struct_name = unwrapped_type.name
        else:
            for name, (llvm_type, _) in self.struct_types.items():
                if str(unwrapped_type) == str(llvm_type):
                    struct_name = name
                    break

        member_val = None
        if struct_name:
            _, field_order = self.struct_types[struct_name]
            if expr.member in field_order:
                field_index = field_order.index(expr.member)
                member_val = self.builder.extract_value(unwrapped, field_index)

        if member_val is None:
            raise ValueError(f"Cannot find field {expr.member} for type {unwrapped_type}")

        # Wrap the result in an optional
        result_optional_type = ir.LiteralStructType([ir.IntType(1), member_val.type])
        some_result = ir.Constant(result_optional_type, ir.Undefined)
        some_result = self.builder.insert_value(some_result, ir.Constant(ir.IntType(1), 1), 0)
        some_result = self.builder.insert_value(some_result, member_val, 1)

        self.builder.branch(merge_bb)
        some_bb = self.builder.block

        # None branch - return None
        self.builder.position_at_start(none_bb)
        none_result = ir.Constant(result_optional_type, ir.Undefined)
        none_result = self.builder.insert_value(none_result, ir.Constant(ir.IntType(1), 0), 0)
        self.builder.branch(merge_bb)
        none_bb = self.builder.block

        # Merge
        self.builder.position_at_start(merge_bb)
        phi = self.builder.phi(result_optional_type, name="chained")
        phi.add_incoming(some_result, some_bb)
        phi.add_incoming(none_result, none_bb)

        return phi

    def _generate_method_call(self, expr: MethodCall):
        """Generate code for method call, static method call, enum initialization, or module function call.

        The parser creates MethodCall for all these cases:
        - object.method(args) - instance method call
        - StructName.method(args) - static method call
        - EnumType.Variant(args) - enum variant initialization
        - ModuleName.function(args) - module function call (Phase 2)
        """
        # Check if this is a module function call or struct init: ModuleName.symbol(args)
        if isinstance(expr.object, Identifier):
            if expr.object.name in self.namespace.modules:
                module_sym = self.namespace.modules[expr.object.name]
                if module_sym.namespace:
                    from namespace import SymbolKind
                    symbol = module_sym.namespace.resolve(expr.method_name)
                    if symbol and symbol.kind == SymbolKind.FUNCTION:
                        # Generate a direct function call (all modules are merged)
                        return self._generate_module_function_call(expr)
                    elif symbol and symbol.kind == SymbolKind.STRUCT:
                        # Generate struct initialization
                        return self._generate_module_struct_init(expr)

        # Check if this is a static method call: StructName.method(args) (use namespace)
        if isinstance(expr.object, Identifier):
            struct_name = expr.object.name
            if self.namespace.is_static_method(struct_name, expr.method_name):
                return self._generate_static_method_call(expr, struct_name)

        # Check if this is actually an enum initialization
        # Check both concrete enums and generic enums
        if isinstance(expr.object, Identifier):
            is_enum = expr.object.name in self.enum_types
            is_generic_enum = expr.object.name in self.generic_enums
            if is_enum or is_generic_enum:
                # Convert to EnumInit and generate it
                enum_init = EnumInit(
                    enum_name=expr.object.name,
                    variant_name=expr.method_name,
                    arguments=expr.arguments,
                    type_args=expr.object.type_args,  # Pass type_args for generic enums
                    line=expr.line,
                    column=expr.column
                )
                return self._generate_enum_init(enum_init)

        # Otherwise, it's a method call
        # Get mangled method name first to check if method expects mutable self
        # We need this info before generating the object expression
        # First, determine struct type by generating the object
        obj_val = self._generate_expression(expr.object)

        # Determine the struct type
        # For identified types, we can get the name directly
        struct_name = None
        obj_type = obj_val.type
        if hasattr(obj_type, 'name') and obj_type.name in self.struct_types:
            # Identified type - name is directly available
            struct_name = obj_type.name
        else:
            # Fallback to string comparison for literal types
            for name, (llvm_type, _) in self.struct_types.items():
                if str(obj_type) == str(llvm_type):
                    struct_name = name
                    break

        # Check for primitive type extensions (String)
        if struct_name is None:
            # String is i8* (pointer to i8)
            if isinstance(obj_type, ir.PointerType):
                pointee = obj_type.pointee
                if isinstance(pointee, ir.IntType) and pointee.width == 8:
                    struct_name = "String"

        if struct_name is None:
            raise ValueError(f"Cannot determine struct type for method call to {expr.method_name}")

        # Get mangled method name
        mangled_name = self._mangle_method_name(struct_name, expr.method_name)

        # Look up the method function
        if mangled_name not in self.functions:
            raise ValueError(f"Undefined method: {struct_name}.{expr.method_name}")

        method_func = self.functions[mangled_name]

        # Generate arguments: [self, arg1, arg2, ...]
        # Check if method expects mutable self (pointer to the value)
        # For String: immutable self is i8*, mutable self is i8**
        # For structs: immutable self is struct, mutable self is struct*
        self_arg = obj_val
        is_mutable_self = False
        if method_func.args:
            first_arg_type = method_func.args[0].type
            if struct_name == "String":
                # String is already i8*, so mutable self is i8** (pointer to pointer)
                if isinstance(first_arg_type, ir.PointerType):
                    pointee = first_arg_type.pointee
                    if isinstance(pointee, ir.PointerType):
                        is_mutable_self = True
            else:
                # Struct: mutable self is pointer to struct
                if isinstance(first_arg_type, ir.PointerType):
                    is_mutable_self = True

        if is_mutable_self:
            # Method expects pointer to self
            # If object is a variable, pass its alloca directly
            if isinstance(expr.object, Identifier) and expr.object.name in self.variables:
                self_arg = self.variables[expr.object.name]
            elif isinstance(expr.object, SelfExpr) and "self" in self.variables:
                # For 'self.method()' in a var self method, pass self's pointer directly
                self_ptr = self.variables["self"]
                # If self is already a pointer (var self method), use it directly
                if isinstance(self_ptr.type, ir.PointerType):
                    self_arg = self_ptr
                else:
                    self_arg = self_ptr  # It's an alloca, pass it
            elif isinstance(expr.object, MemberAccess):
                # Handle nested mutable access like self.keys.push(...)
                # We need a pointer to the field, not a copy
                self_arg = self._get_member_pointer(expr.object)
            else:
                # Otherwise create a temporary
                self_alloca = self.builder.alloca(obj_val.type, name="self_temp")
                self.builder.store(obj_val, self_alloca)
                self_arg = self_alloca

        args = [self_arg]  # self is first argument
        # Arguments are Argument objects with .value
        for arg in expr.arguments:
            args.append(self._generate_expression(arg.value))

        # Fill in default values for missing arguments
        if mangled_name in self.method_defaults:
            defaults = self.method_defaults[mangled_name]
            # defaults includes self, so adjust index: args[0] is self, defaults[0] is self
            for i in range(len(args), len(defaults)):
                if defaults[i] is not None:
                    args.append(self._generate_expression(defaults[i]))

        # Call the method
        return self.builder.call(method_func, args, name="methodcall")

    def _generate_static_method_call(self, expr: MethodCall, struct_name: str):
        """Generate a static method call: StructName.method(args)"""
        mangled_name = self._mangle_method_name(struct_name, expr.method_name)

        if mangled_name not in self.functions:
            raise ValueError(f"Undefined static method: {struct_name}.{expr.method_name}")

        method_func = self.functions[mangled_name]

        # Generate provided arguments
        args = []
        for arg in expr.arguments:
            args.append(self._generate_expression(arg.value))

        # Fill in default values for missing arguments
        if mangled_name in self.method_defaults:
            defaults = self.method_defaults[mangled_name]
            for i in range(len(args), len(defaults)):
                if defaults[i] is not None:
                    args.append(self._generate_expression(defaults[i]))

        return self.builder.call(method_func, args, name="static_methodcall")

    def _generate_module_function_call(self, expr: MethodCall):
        """Generate a module function call: ModuleName.function(args)

        Since all modules are merged, we can call the function directly.
        """
        func_name = expr.method_name

        if func_name not in self.functions:
            raise ValueError(f"Undefined function in module: {expr.object.name}.{func_name}")

        func = self.functions[func_name]

        # Generate arguments
        args = []
        for arg in expr.arguments:
            args.append(self._generate_expression(arg.value))

        return self.builder.call(func, args, name="module_call")

    def _generate_module_struct_init(self, expr: MethodCall):
        """Generate a module struct initialization: ModuleName.StructName(args)

        Since all modules are merged, the struct exists in the global namespace.
        """
        struct_name = expr.method_name

        # Convert MethodCall to StructInit
        struct_init = StructInit(
            struct_name=struct_name,
            field_inits=[],
            type_args=None,
            line=expr.line,
            column=expr.column
        )

        # Handle arguments
        # struct_types[name] = (llvm_type, field_order) where field_order is a list
        if struct_name in self.struct_types:
            _, field_order = self.struct_types[struct_name]

            # Map arguments to fields
            for i, arg in enumerate(expr.arguments):
                if arg.name:
                    # Named argument
                    struct_init.field_inits.append((arg.name, arg.value))
                elif i < len(field_order):
                    # Positional argument - map to field by order
                    struct_init.field_inits.append((field_order[i], arg.value))

        return self._generate_struct_init(struct_init)

    def _get_member_pointer(self, expr: MemberAccess):
        """Get a pointer to a struct field for mutable access.

        For expressions like self.keys where we need to mutate keys in place,
        this returns a GEP pointer to the field rather than extracting a copy.
        """
        # Get pointer to the base object
        if isinstance(expr.object, Identifier) and expr.object.name in self.variables:
            base_ptr = self.variables[expr.object.name]
        elif isinstance(expr.object, SelfExpr) and "self" in self.variables:
            base_ptr = self.variables["self"]
        elif isinstance(expr.object, MemberAccess):
            # Recursive case: nested member access like a.b.c
            base_ptr = self._get_member_pointer(expr.object)
        else:
            # Fallback: create temporary (won't propagate changes back)
            base_val = self._generate_expression(expr.object)
            base_ptr = self.builder.alloca(base_val.type, name="member_temp")
            self.builder.store(base_val, base_ptr)

        # Determine the struct type
        ptr_type = base_ptr.type
        if isinstance(ptr_type, ir.PointerType):
            struct_type = ptr_type.pointee
        else:
            raise ValueError(f"Expected pointer type, got {ptr_type}")

        # Find struct name
        struct_name = None
        if hasattr(struct_type, 'name') and struct_type.name in self.struct_types:
            struct_name = struct_type.name
        else:
            for name, (llvm_type, _) in self.struct_types.items():
                if str(struct_type) == str(llvm_type):
                    struct_name = name
                    break

        if struct_name is None:
            raise ValueError(f"Cannot find struct type for member access: {expr.member}")

        # Get field index
        _, field_order = self.struct_types[struct_name]
        if expr.member not in field_order:
            raise ValueError(f"Unknown field: {struct_name}.{expr.member}")
        field_index = field_order.index(expr.member)

        # GEP to get pointer to the field
        zero = ir.Constant(ir.IntType(32), 0)
        field_idx = ir.Constant(ir.IntType(32), field_index)
        return self.builder.gep(base_ptr, [zero, field_idx], name=f"{expr.member}_ptr")

    def _generate_self_expr(self, expr: SelfExpr):
        """Generate code for 'self' keyword."""
        if "self" not in self.variables:
            raise ValueError("'self' not found in current scope")

        # Load self from its alloca
        return self.builder.load(self.variables["self"], name="self")

    def _generate_enum_init(self, expr: EnumInit):
        """Generate code for enum variant initialization."""
        # Handle generic enum with type_args
        enum_name = expr.enum_name
        if expr.type_args:
            enum_name = self._ensure_monomorphized_enum(expr.enum_name, expr.type_args)

        if enum_name not in self.enum_types:
            raise ValueError(f"Undefined enum: {enum_name}")

        llvm_enum_type, variant_tags, variant_info = self.enum_types[enum_name]
        tag_value = variant_tags[expr.variant_name]
        variant_params = variant_info[expr.variant_name]

        # Check if this is a simple enum (just i32) or enum with payload
        if isinstance(llvm_enum_type, ir.IntType):
            # Simple enum: just return the tag value
            return ir.Constant(ir.IntType(32), tag_value)
        else:
            # Enum with payload: { i32 tag, [N x i8] payload }
            # Create undefined struct value
            enum_val = ir.Constant(llvm_enum_type, ir.Undefined)

            # Insert tag value
            tag_const = ir.Constant(ir.IntType(32), tag_value)
            enum_val = self.builder.insert_value(enum_val, tag_const, 0, name="enum_with_tag")

            # If this variant has associated values, pack them into payload
            if variant_params:
                # Generate values for arguments
                # Arguments are Argument objects with .value and optional .name
                arg_values = []

                # Build a dict for named args, list for positional
                arg_dict = {}
                arg_list = []
                for arg in expr.arguments:
                    if arg.is_named:
                        arg_dict[arg.name] = arg.value
                    else:
                        arg_list.append(arg.value)

                # Match arguments to parameters (named takes precedence, then positional)
                for i, (param_name, param_type) in enumerate(variant_params):
                    if param_name in arg_dict:
                        arg_val = self._generate_expression(arg_dict[param_name])
                    elif i < len(arg_list):
                        arg_val = self._generate_expression(arg_list[i])
                    else:
                        raise ValueError(f"Missing argument for parameter {param_name}")
                    arg_values.append(arg_val)

                # Create a struct for the associated values
                param_struct_type = ir.LiteralStructType([self._get_llvm_type(t) for _, t in variant_params])
                param_struct = ir.Constant(param_struct_type, ir.Undefined)
                for i, val in enumerate(arg_values):
                    param_struct = self.builder.insert_value(param_struct, val, i, name=f"param{i}")

                # Cast the param struct to bytes and store in payload
                # For simplicity, we'll use bitcast + store
                payload_array_type = llvm_enum_type.elements[1]  # [N x i8]

                # Allocate temporary space for the payload
                payload_temp = self.builder.alloca(param_struct_type, name="payload_temp")
                self.builder.store(param_struct, payload_temp)

                # Bitcast to array of bytes
                payload_ptr = self.builder.bitcast(payload_temp,
                                                   ir.PointerType(ir.IntType(8)),
                                                   name="payload_bytes_ptr")

                # Load bytes into an array value
                payload_bytes = ir.Constant(payload_array_type, ir.Undefined)
                for i in range(payload_array_type.count):
                    idx_ptr = self.builder.gep(payload_ptr,
                                              [ir.Constant(ir.IntType(32), i)],
                                              inbounds=True)
                    byte_val = self.builder.load(idx_ptr, name=f"byte{i}")
                    payload_bytes = self.builder.insert_value(payload_bytes, byte_val, i, name=f"payload{i}")

                # Insert payload into enum
                enum_val = self.builder.insert_value(enum_val, payload_bytes, 1, name="enum_with_payload")

            return enum_val

    def _generate_match_expr(self, expr: MatchExpr):
        """Generate code for match expression."""
        # Generate the matched value
        matched_val = self._generate_expression(expr.matched_expr)

        # Extract the tag
        # Check if enum is simple (i32) or has payload ({ i32, [N x i8] })
        if isinstance(matched_val.type, ir.IntType):
            # Simple enum
            tag = matched_val
        else:
            # Enum with payload
            tag = self.builder.extract_value(matched_val, 0, name="match_tag")

        # Find the enum name by matching LLVM types
        enum_name = None
        for name, (llvm_type, _, _) in self.enum_types.items():
            if llvm_type == matched_val.type:
                enum_name = name
                break

        # Create basic blocks for each arm + merge block
        arm_blocks = []
        wildcard_block = None
        for arm in expr.arms:
            arm_block = self.builder.append_basic_block(f"match_arm_{arm.variant_name}")
            arm_blocks.append((arm, arm_block))
            if arm.variant_name == "_":
                wildcard_block = arm_block

        merge_block = self.builder.append_basic_block("match_merge")

        # Create switch instruction
        # Use wildcard as default if present, otherwise first arm
        default_block = wildcard_block if wildcard_block else arm_blocks[0][1]
        switch = self.builder.switch(tag, default_block)

        # Add cases for non-wildcard arms
        if enum_name:
            _, variant_tags, variant_info = self.enum_types[enum_name]
            for arm, arm_block in arm_blocks:
                # Skip wildcard - it's the default case
                if arm.variant_name == "_":
                    continue
                tag_value = variant_tags[arm.variant_name]
                tag_const = ir.Constant(ir.IntType(32), tag_value)
                switch.add_case(tag_const, arm_block)

        # Generate code for each arm
        arm_results = []
        for arm, arm_block in arm_blocks:
            self.builder.position_at_end(arm_block)

            # Extract and bind associated values if any (not for wildcard)
            if arm.variant_name != "_" and arm.bindings and not isinstance(matched_val.type, ir.IntType):
                # Get variant info and enum type
                llvm_enum_type, _, variant_info = self.enum_types[enum_name]
                variant_params = variant_info[arm.variant_name]

                # Extract payload
                payload_bytes = self.builder.extract_value(matched_val, 1, name="payload")

                # Cast to appropriate struct type
                param_types = [self._get_llvm_type(t) for _, t in variant_params]
                param_struct_type = ir.LiteralStructType(param_types)

                # Store bytes to memory, then load as struct
                payload_alloca = self.builder.alloca(llvm_enum_type.elements[1], name="payload_alloca")
                self.builder.store(payload_bytes, payload_alloca)
                struct_ptr = self.builder.bitcast(payload_alloca,
                                                  ir.PointerType(param_struct_type),
                                                  name="param_struct_ptr")

                # Create variables for bindings
                for i, binding_name in enumerate(arm.bindings):
                    # Extract field from struct
                    field_ptr = self.builder.gep(struct_ptr,
                                                [ir.Constant(ir.IntType(32), 0),
                                                 ir.Constant(ir.IntType(32), i)],
                                                inbounds=True)
                    field_val = self.builder.load(field_ptr, name=binding_name)

                    # Store in a variable
                    var_alloca = self.builder.alloca(field_val.type, name=binding_name)
                    self.builder.store(field_val, var_alloca)
                    self.variables[binding_name] = var_alloca

            # Generate arm body
            if isinstance(arm.body, Block):
                arm_result = self._generate_block(arm.body)
                # Get the value from the block
                if arm_result is None:
                    # Block didn't have a value, use void or a placeholder
                    arm_result = ir.Constant(ir.IntType(32), 0)  # Placeholder
            else:
                arm_result = self._generate_expression(arm.body)

            arm_results.append((arm_result, self.builder.block))

            # Clean up bindings
            for binding_name in arm.bindings:
                if binding_name in self.variables:
                    del self.variables[binding_name]

            # Branch to merge block
            self.builder.branch(merge_block)

        # Position at merge block
        self.builder.position_at_end(merge_block)

        # Create phi node to merge results
        if arm_results and arm_results[0][0] is not None:
            result_type = arm_results[0][0].type
            phi = self.builder.phi(result_type, name="match_result")
            for val, block in arm_results:
                phi.add_incoming(val, block)
            return phi
        else:
            # Match doesn't produce a value
            return None

    def _generate_closure(self, expr: ClosureExpr):
        """Generate code for a closure expression."""
        # Determine closure parameter and return types
        param_types = []
        param_names = []

        if expr.parameters:
            for param in expr.parameters:
                if param.type_annotation:
                    param_types.append(self._get_llvm_type(param.type_annotation))
                else:
                    # Type should have been inferred by typechecker
                    # For now, use Int as fallback
                    param_types.append(ir.IntType(64))
                param_names.append(param.name)
        elif expr.shorthand_param_count > 0:
            # Shorthand params - types should be inferred
            for i in range(expr.shorthand_param_count):
                param_types.append(ir.IntType(64))  # Fallback type
                param_names.append(f"${i}")

        # Get return type from body (we'll determine during generation)
        # For now, assume Int or Void based on whether body has final_expr
        if expr.body.final_expr:
            ret_type = ir.IntType(64)  # Default return type
        else:
            ret_type = ir.VoidType()

        # Create environment struct type for captures
        env_ptr_type = ir.PointerType(ir.IntType(8))
        captures = expr.captures or []

        if captures:
            # Build environment struct with captured variables
            env_field_types = []
            for cap_name in captures:
                if cap_name in self.variable_types:
                    cap_type = self._get_llvm_type(self.variable_types[cap_name])
                elif cap_name in self.variables:
                    # Get type from the alloca
                    alloca = self.variables[cap_name]
                    cap_type = alloca.type.pointee
                else:
                    cap_type = ir.IntType(64)  # Fallback
                env_field_types.append(cap_type)
            env_struct_type = ir.LiteralStructType(env_field_types)
        else:
            env_struct_type = None

        # Create unique name for closure function
        closure_name = f"__closure_{self.closure_counter}"
        self.closure_counter += 1

        # Create closure function type: (env_ptr, params...) -> ret
        fn_param_types = [env_ptr_type] + param_types
        fn_type = ir.FunctionType(ret_type, fn_param_types)

        # Create the closure function
        closure_fn = ir.Function(self.module, fn_type, name=closure_name)

        # Save current builder and variables
        saved_builder = self.builder
        saved_variables = self.variables.copy()
        saved_variable_types = self.variable_types.copy()
        saved_cleanup_stack = self.cleanup_stack[:]

        # Generate closure body
        entry = closure_fn.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(entry)
        self.variables = {}
        self.variable_types = {}
        self.cleanup_stack = []

        # Set up environment access if there are captures
        if captures and env_struct_type:
            env_ptr_arg = closure_fn.args[0]
            typed_env_ptr = self.builder.bitcast(
                env_ptr_arg,
                ir.PointerType(env_struct_type),
                name="env_typed"
            )
            for i, cap_name in enumerate(captures):
                field_ptr = self.builder.gep(
                    typed_env_ptr,
                    [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), i)],
                    name=f"cap_{cap_name}_ptr"
                )
                # Load the captured value
                cap_value = self.builder.load(field_ptr, name=f"cap_{cap_name}")
                # Store in a local alloca so it can be used like a variable
                alloca = self.builder.alloca(cap_value.type, name=cap_name)
                self.builder.store(cap_value, alloca)
                self.variables[cap_name] = alloca

        # Set up parameter access
        for i, param_name in enumerate(param_names):
            llvm_param = closure_fn.args[i + 1]  # +1 for env_ptr
            alloca = self.builder.alloca(param_types[i], name=param_name)
            self.builder.store(llvm_param, alloca)
            self.variables[param_name] = alloca

        # Generate body
        result = self._generate_block(expr.body)

        # Return
        if ret_type == ir.VoidType():
            if not self.builder.block.is_terminated:
                self.builder.ret_void()
        else:
            if not self.builder.block.is_terminated:
                if result is not None:
                    self.builder.ret(result)
                else:
                    self.builder.ret(ir.Constant(ret_type, 0))

        # Restore context
        self.builder = saved_builder
        self.variables = saved_variables
        self.variable_types = saved_variable_types
        self.cleanup_stack = saved_cleanup_stack

        # Create environment struct on stack and copy captured values
        if captures and env_struct_type:
            env_alloca = self.builder.alloca(env_struct_type, name="closure_env")
            for i, cap_name in enumerate(captures):
                if cap_name in self.variables:
                    cap_value = self.builder.load(self.variables[cap_name], name=f"load_{cap_name}")
                    field_ptr = self.builder.gep(
                        env_alloca,
                        [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), i)],
                        name=f"env_field_{i}"
                    )
                    self.builder.store(cap_value, field_ptr)
            env_ptr_val = self.builder.bitcast(env_alloca, env_ptr_type, name="env_ptr")
        else:
            env_ptr_val = ir.Constant(env_ptr_type, None)

        # Create closure struct: { fn_ptr, env_ptr }
        closure_type = ir.LiteralStructType([ir.PointerType(fn_type), env_ptr_type])
        closure_val = ir.Constant(closure_type, ir.Undefined)
        closure_val = self.builder.insert_value(closure_val, closure_fn, 0, name="closure_fn")
        closure_val = self.builder.insert_value(closure_val, env_ptr_val, 1, name="closure_env")

        return closure_val

    def _generate_closure_call(self, closure_val, arguments):
        """Generate code for calling a closure stored in a variable."""
        # Extract fn_ptr and env_ptr from closure struct
        fn_ptr = self.builder.extract_value(closure_val, 0, name="fn_ptr")
        env_ptr = self.builder.extract_value(closure_val, 1, name="env_ptr")

        # Generate argument values
        arg_vals = [self._generate_expression(arg) for arg in arguments]

        # Call: fn_ptr(env_ptr, arg1, arg2, ...)
        return self.builder.call(fn_ptr, [env_ptr] + arg_vals, name="closure_call")

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

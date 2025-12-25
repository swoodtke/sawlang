"""
Saw Language Code Generator
Generates LLVM IR from the AST using llvmlite.
"""

from typing import Optional, List
from llvmlite import ir, binding
from ast_nodes import (
    Program, Function, Block, Statement, Expression,
    LetStatement, AssignStatement, ReturnStatement, ExpressionStatement,
    IntLiteral, FloatLiteral, BoolLiteral, StringLiteral, Identifier,
    BinaryOp, UnaryOp, FunctionCall, IfExpr, IfLetExpr,
    TupleLiteral, TupleIndex, MemberAccess, StructInit,
    NoneLiteral, ForceUnwrap, NilCoalesce, OptionalChain,
    GuardLetStatement,
    Struct, StructField,
    Enum, EnumVariant, EnumInit, MatchExpr, MatchArm,
    Extension, Method, MethodCall, SelfExpr,
    SawType, TypeKind, Argument
)


class CodeGenerator:
    def __init__(self):
        # Initialize LLVM
        binding.initialize()
        binding.initialize_native_target()
        binding.initialize_native_asmprinter()

        # Create module
        self.module = ir.Module(name="saw_module")
        self.module.triple = binding.get_default_triple()

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

    def _get_llvm_type(self, saw_type: SawType) -> ir.Type:
        if saw_type.kind == TypeKind.INT:
            return ir.IntType(64)
        elif saw_type.kind == TypeKind.FLOAT:
            return ir.DoubleType()
        elif saw_type.kind == TypeKind.BOOL:
            return ir.IntType(1)
        elif saw_type.kind == TypeKind.STRING:
            return ir.PointerType(ir.IntType(8))
        elif saw_type.kind == TypeKind.VOID:
            return ir.VoidType()
        elif saw_type.kind == TypeKind.TUPLE:
            # Tuples are represented as LLVM structs
            if saw_type.element_types is None:
                return ir.LiteralStructType([])
            element_llvm_types = [self._get_llvm_type(t) for t in saw_type.element_types]
            return ir.LiteralStructType(element_llvm_types)
        elif saw_type.kind == TypeKind.STRUCT:
            # Look up the struct type (might actually be an enum)
            if saw_type.struct_name is None:
                raise ValueError("Struct type missing name")
            # Check if it's actually an enum
            if saw_type.struct_name in self.enum_types:
                return self.enum_types[saw_type.struct_name][0]  # Return LLVM type
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
            if saw_type.enum_name not in self.enum_types:
                raise ValueError(f"Undefined enum: {saw_type.enum_name}")
            return self.enum_types[saw_type.enum_name][0]  # Return LLVM type
        else:
            raise ValueError(f"Unknown type: {saw_type}")

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
        # First pass: register struct types
        for struct in program.structs:
            self._register_struct(struct)

        # Second pass: register enum types
        for enum in program.enums:
            self._register_enum(enum)

        # Third pass: declare all functions
        for func in program.functions:
            self._declare_function(func)

        # Declare extension methods
        for extension in program.extensions:
            self._declare_extension_methods(extension)

        # Fourth pass: generate function bodies
        for func in program.functions:
            self._generate_function(func)

        # Generate extension method bodies
        for extension in program.extensions:
            self._generate_extension_methods(extension)

        return str(self.module)

    def _register_struct(self, struct: Struct):
        """Register a struct type with LLVM."""
        # Get LLVM types for each field
        field_types = [self._get_llvm_type(field.type) for field in struct.fields]

        # Create LLVM struct type
        llvm_struct_type = ir.LiteralStructType(field_types)

        # Store the type and field order for later use
        field_order = [field.name for field in struct.fields]
        self.struct_types[struct.name] = (llvm_struct_type, field_order)

    def _register_enum(self, enum: Enum):
        """Register an enum type with LLVM.
        Enums are represented as tagged unions: { i32 tag, [N x i8] payload }
        or just i32 if all variants have no associated values."""
        # Assign tag values to variants (0, 1, 2, ...)
        variant_tags = {}
        variant_info = {}
        max_payload_size = 0

        for i, variant in enumerate(enum.variants):
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
        self.enum_types[enum.name] = (llvm_enum_type, variant_tags, variant_info)

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

    def _declare_function(self, func: Function):
        param_types = [self._get_llvm_type(p.type) for p in func.parameters]
        return_type = self._get_llvm_type(func.return_type)

        # Main function should return int for proper exit code
        if func.name == "main" and func.return_type.kind == TypeKind.VOID:
            return_type = ir.IntType(32)

        func_type = ir.FunctionType(return_type, param_types)
        llvm_func = ir.Function(self.module, func_type, name=func.name)
        self.functions[func.name] = llvm_func

    def _mangle_method_name(self, struct_name: str, method_name: str, param_names: Optional[List[str]] = None) -> str:
        """Generate mangled name for methods: StructName_methodName
           For init methods, include parameter names to allow overloading."""
        if param_names is not None:
            # Init method - include parameter signature
            param_sig = '_'.join(param_names)
            return f"{struct_name}_{method_name}_{param_sig}"
        else:
            return f"{struct_name}_{method_name}"

    def _declare_extension_methods(self, extension: Extension):
        """Declare all methods in an extension."""
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
                param_types = [self._get_llvm_type(p.type) for p in method.parameters]
                # Return type is the struct being initialized
                struct_type, _ = self.struct_types[extension.struct_name]
                return_type = struct_type
            else:
                # Regular methods include self as first parameter
                param_types = []
                for i, p in enumerate(method.parameters):
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

    def _generate_extension_methods(self, extension: Extension):
        """Generate code for all methods in an extension."""
        for method in extension.methods:
            if method.is_init:
                self._generate_init_method(extension.struct_name, method)
            else:
                self._generate_method(extension.struct_name, method)

    def _generate_method(self, struct_name: str, method: Method):
        """Generate code for a single method."""
        mangled_name = self._mangle_method_name(struct_name, method.name)
        llvm_func = self.functions[mangled_name]

        # Create entry block
        block = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(block)

        # Clear variables for this method
        self.variables = {}

        # Create allocas for parameters (including self)
        for i, param in enumerate(method.parameters):
            llvm_func.args[i].name = param.name
            # For mutable self, it's already a pointer - just store it directly
            if i == 0 and param.name == "self" and method.self_mutable:
                self.variables[param.name] = llvm_func.args[i]
            else:
                alloca = self.builder.alloca(self._get_llvm_type(param.type), name=param.name)
                self.builder.store(llvm_func.args[i], alloca)
                self.variables[param.name] = alloca

        # Generate method body
        result = self._generate_block(method.body)

        # Handle return
        if method.return_type.kind == TypeKind.VOID:
            if not self.builder.block.is_terminated:
                self.builder.ret_void()
        else:
            if not self.builder.block.is_terminated:
                if result is not None:
                    self.builder.ret(result)
                else:
                    # Return default value
                    default = ir.Constant(self._get_llvm_type(method.return_type), 0)
                    self.builder.ret(default)

    def _generate_init_method(self, struct_name: str, method: Method):
        """Generate code for a custom init method."""
        param_names = [p.name for p in method.parameters]
        mangled_name = self._mangle_method_name(struct_name, method.name, param_names)
        llvm_func = self.functions[mangled_name]

        # Create entry block
        block = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(block)

        # Clear variables for this method
        self.variables = {}

        # Create allocas for parameters (no self for init methods)
        for i, param in enumerate(method.parameters):
            llvm_func.args[i].name = param.name
            alloca = self.builder.alloca(self._get_llvm_type(param.type), name=param.name)
            self.builder.store(llvm_func.args[i], alloca)
            self.variables[param.name] = alloca

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

    def _generate_function(self, func: Function):
        llvm_func = self.functions[func.name]

        # Create entry block
        block = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(block)

        # Clear variables for this function
        self.variables = {}

        # Create allocas for parameters
        for i, param in enumerate(func.parameters):
            llvm_func.args[i].name = param.name
            alloca = self.builder.alloca(self._get_llvm_type(param.type), name=param.name)
            self.builder.store(llvm_func.args[i], alloca)
            self.variables[param.name] = alloca

        # Generate function body
        result = self._generate_block(func.body)

        # Handle return
        if func.return_type.kind == TypeKind.VOID:
            if not self.builder.block.is_terminated:
                # For main(), return 0 instead of void
                if func.name == "main":
                    self.builder.ret(ir.Constant(ir.IntType(32), 0))
                else:
                    self.builder.ret_void()
        else:
            if not self.builder.block.is_terminated:
                if result is not None:
                    self.builder.ret(result)
                else:
                    # Return default value
                    default = ir.Constant(self._get_llvm_type(func.return_type), 0)
                    self.builder.ret(default)

    def _generate_block(self, block: Block):
        result = None

        for stmt in block.statements:
            self._generate_statement(stmt)
            if self.builder.block.is_terminated:
                return None

        if block.final_expr is not None:
            result = self._generate_expression(block.final_expr)

        return result

    def _generate_statement(self, stmt: Statement):
        if isinstance(stmt, LetStatement):
            self._generate_let_statement(stmt)
        elif isinstance(stmt, AssignStatement):
            self._generate_assign_statement(stmt)
        elif isinstance(stmt, ReturnStatement):
            self._generate_return_statement(stmt)
        elif isinstance(stmt, GuardLetStatement):
            self._generate_guard_let_statement(stmt)
        elif isinstance(stmt, ExpressionStatement):
            self._generate_expression(stmt.expression)
        else:
            raise ValueError(f"Unknown statement type: {type(stmt)}")

    def _generate_let_statement(self, stmt: LetStatement):
        value = self._generate_expression(stmt.value)

        # Check if we need to wrap the value in an optional
        if stmt.type_annotation and stmt.type_annotation.kind == TypeKind.OPTIONAL:
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
                target_inner_type = self._get_llvm_type(stmt.type_annotation.inner_type)

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

    def _generate_assign_statement(self, stmt: AssignStatement):
        value = self._generate_expression(stmt.value)

        if isinstance(stmt.target, Identifier):
            # Simple variable assignment
            if stmt.target.name not in self.variables:
                raise ValueError(f"Undefined variable: {stmt.target.name}")
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
            else:
                raise ValueError(f"Unsupported object expression in field assignment: {type(obj_expr)}")

            # Determine struct type and field index
            # Get the actual struct type (dereference if it's a pointer)
            if isinstance(struct_ptr.type.pointee, ir.LiteralStructType):
                llvm_struct_type = struct_ptr.type.pointee
            else:
                raise ValueError(f"Cannot assign to field of non-struct type")

            # Find which struct this is
            struct_name = None
            for name, (st, _) in self.struct_types.items():
                if isinstance(st, ir.LiteralStructType) and str(st) == str(llvm_struct_type):
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

            # Store value to field
            self.builder.store(value, field_ptr)

        else:
            raise ValueError(f"Invalid assignment target: {type(stmt.target)}")

    def _generate_return_statement(self, stmt: ReturnStatement):
        if stmt.value is not None:
            value = self._generate_expression(stmt.value)
            self.builder.ret(value)
        else:
            self.builder.ret_void()

    def _generate_expression(self, expr: Expression):
        if isinstance(expr, IntLiteral):
            return ir.Constant(ir.IntType(64), expr.value)

        elif isinstance(expr, FloatLiteral):
            return ir.Constant(ir.DoubleType(), expr.value)

        elif isinstance(expr, BoolLiteral):
            return ir.Constant(ir.IntType(1), 1 if expr.value else 0)

        elif isinstance(expr, StringLiteral):
            global_str = self._create_string_constant(expr.value)
            zero = ir.Constant(ir.IntType(32), 0)
            return self.builder.gep(global_str, [zero, zero], inbounds=True)

        elif isinstance(expr, Identifier):
            if expr.name not in self.variables:
                raise ValueError(f"Undefined variable: {expr.name}")
            return self.builder.load(self.variables[expr.name], name=expr.name)

        elif isinstance(expr, BinaryOp):
            return self._generate_binary_op(expr)

        elif isinstance(expr, UnaryOp):
            return self._generate_unary_op(expr)

        elif isinstance(expr, FunctionCall):
            return self._generate_function_call(expr)

        elif isinstance(expr, IfExpr):
            return self._generate_if_expression(expr)

        elif isinstance(expr, IfLetExpr):
            return self._generate_if_let_expression(expr)

        elif isinstance(expr, TupleLiteral):
            return self._generate_tuple_literal(expr)

        elif isinstance(expr, TupleIndex):
            return self._generate_tuple_index(expr)

        elif isinstance(expr, MemberAccess):
            return self._generate_member_access(expr)

        elif isinstance(expr, StructInit):
            return self._generate_struct_init(expr)

        elif isinstance(expr, NoneLiteral):
            return self._generate_none_literal(expr)

        elif isinstance(expr, ForceUnwrap):
            return self._generate_force_unwrap(expr)

        elif isinstance(expr, NilCoalesce):
            return self._generate_nil_coalesce(expr)

        elif isinstance(expr, OptionalChain):
            return self._generate_optional_chain(expr)

        elif isinstance(expr, MethodCall):
            return self._generate_method_call(expr)

        elif isinstance(expr, SelfExpr):
            return self._generate_self_expr(expr)

        elif isinstance(expr, EnumInit):
            return self._generate_enum_init(expr)

        elif isinstance(expr, MatchExpr):
            return self._generate_match_expr(expr)

        else:
            raise ValueError(f"Unknown expression type: {type(expr)}")

    def _generate_binary_op(self, expr: BinaryOp):
        left = self._generate_expression(expr.left)
        right = self._generate_expression(expr.right)

        # Check if we're dealing with floats
        is_float = isinstance(left.type, ir.DoubleType)

        if expr.op == '+':
            if is_float:
                return self.builder.fadd(left, right, name="addtmp")
            return self.builder.add(left, right, name="addtmp")

        elif expr.op == '-':
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

    def _generate_unary_op(self, expr: UnaryOp):
        operand = self._generate_expression(expr.operand)

        if expr.op == '-':
            if isinstance(operand.type, ir.DoubleType):
                return self.builder.fneg(operand, name="negtmp")
            zero = ir.Constant(ir.IntType(64), 0)
            return self.builder.sub(zero, operand, name="negtmp")

        else:
            raise ValueError(f"Unknown unary operator: {expr.op}")

    def _generate_function_call(self, expr: FunctionCall):
        # Handle built-in print function
        if expr.name == "print":
            return self._generate_print(expr.arguments)

        # Look up user-defined function
        if expr.name not in self.functions:
            raise ValueError(f"Undefined function: {expr.name}")

        func = self.functions[expr.name]
        # Arguments are now Argument objects with .value
        args = [self._generate_expression(arg.value) for arg in expr.arguments]
        return self.builder.call(func, args, name="calltmp")

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
                # Integer
                fmt = self._create_string_constant("%lld\n")
                zero = ir.Constant(ir.IntType(32), 0)
                fmt_ptr = self.builder.gep(fmt, [zero, zero], inbounds=True)
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
        if not self.builder.block.is_terminated:
            self.builder.branch(merge_bb)
        then_bb = self.builder.block

        # Generate else branch
        self.builder.position_at_start(else_bb)
        if expr.else_branch:
            else_val = self._generate_block(expr.else_branch)
        else:
            else_val = None
        if not self.builder.block.is_terminated:
            self.builder.branch(merge_bb)
        else_bb = self.builder.block

        # Merge block
        self.builder.position_at_start(merge_bb)

        # If both branches produce values of the same type, create a phi node
        if then_val is not None and else_val is not None:
            if then_val.type == else_val.type:
                phi = self.builder.phi(then_val.type, name="iftmp")
                phi.add_incoming(then_val, then_bb)
                phi.add_incoming(else_val, else_bb)
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

        then_val = self._generate_block(expr.then_branch)

        # Remove the bound variable from scope after the block
        del self.variables[expr.name]

        if not self.builder.block.is_terminated:
            self.builder.branch(merge_bb)
        then_bb = self.builder.block

        # Generate else branch
        self.builder.position_at_start(else_bb)
        if expr.else_branch:
            else_val = self._generate_block(expr.else_branch)
        else:
            else_val = None
        if not self.builder.block.is_terminated:
            self.builder.branch(merge_bb)
        else_bb = self.builder.block

        # Merge block
        self.builder.position_at_start(merge_bb)

        # If both branches produce values of the same type, create a phi node
        if then_val is not None and else_val is not None:
            if then_val.type == else_val.type:
                phi = self.builder.phi(then_val.type, name="if_let_result")
                phi.add_incoming(then_val, then_bb)
                phi.add_incoming(else_val, else_bb)
                return phi

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

    def _generate_struct_init(self, expr: StructInit):
        """Generate code for struct initialization."""
        if expr.struct_name not in self.struct_types:
            raise ValueError(f"Undefined struct: {expr.struct_name}")

        # Check if this is a custom init method call
        if expr.resolved_init_params is not None:
            # Custom init - call the init method
            mangled_name = self._mangle_method_name(expr.struct_name, "init", expr.resolved_init_params)
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
        llvm_struct_type, field_order = self.struct_types[expr.struct_name]

        # Create a map from field name to value
        field_values = {field_name: self._generate_expression(value)
                       for field_name, value in expr.field_inits}

        # Build the struct value in the correct field order
        struct_val = ir.Constant(llvm_struct_type, ir.Undefined)
        for i, field_name in enumerate(field_order):
            if field_name in field_values:
                struct_val = self.builder.insert_value(struct_val, field_values[field_name], i)

        return struct_val

    def _generate_member_access(self, expr: MemberAccess):
        """Generate code for member access on structs or enum variant access."""
        # Special case: EnumName.VariantName (simple variant with no associated values)
        if isinstance(expr.object, Identifier) and expr.object.name in self.enum_types:
            # This is an enum variant access - convert to EnumInit
            enum_init = EnumInit(
                enum_name=expr.object.name,
                variant_name=expr.member,
                arguments=[],
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

        # Find the matching struct type and field index
        for struct_name, (llvm_type, field_order) in self.struct_types.items():
            # Compare struct types by structure
            if (isinstance(obj_type, ir.LiteralStructType) and
                isinstance(llvm_type, ir.LiteralStructType) and
                str(obj_type) == str(llvm_type)):
                if expr.member in field_order:
                    field_index = field_order.index(expr.member)
                    return self.builder.extract_value(obj_val, field_index)

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

    def _generate_none_literal(self, expr: NoneLiteral):
        """Generate code for None literal."""
        # Create an optional with is_some = false
        # We use i64 as a placeholder type since None can be any optional type
        optional_type = ir.LiteralStructType([ir.IntType(1), ir.IntType(64)])
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

        # TODO: Add runtime check - for now, just extract the value
        # In a full implementation, we'd check is_some and panic if false

        # Extract and return the value
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
        member_val = None
        for struct_name, (llvm_type, field_order) in self.struct_types.items():
            # Compare struct types by checking if they're both LiteralStructType with same elements
            if (isinstance(unwrapped.type, ir.LiteralStructType) and
                isinstance(llvm_type, ir.LiteralStructType) and
                str(unwrapped.type) == str(llvm_type)):
                if expr.member in field_order:
                    field_index = field_order.index(expr.member)
                    member_val = self.builder.extract_value(unwrapped, field_index)
                    break

        if member_val is None:
            raise ValueError(f"Cannot find field {expr.member} for type {unwrapped.type}")

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
        """Generate code for method call or enum initialization: object.method(args).

        The parser creates MethodCall for both cases. This method disambiguates
        based on whether 'object' is an Identifier that matches an enum name.
        """
        # Check if this is actually an enum initialization
        if isinstance(expr.object, Identifier) and expr.object.name in self.enum_types:
            # Convert to EnumInit and generate it
            enum_init = EnumInit(
                enum_name=expr.object.name,
                variant_name=expr.method_name,
                arguments=expr.arguments,
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
        # Find which struct this is by matching LLVM type
        struct_name = None
        for name, (llvm_type, _) in self.struct_types.items():
            if (isinstance(obj_val.type, ir.LiteralStructType) and
                isinstance(llvm_type, ir.LiteralStructType) and
                str(obj_val.type) == str(llvm_type)):
                struct_name = name
                break

        if struct_name is None:
            raise ValueError(f"Cannot determine struct type for method call to {expr.method_name}")

        # Get mangled method name
        mangled_name = self._mangle_method_name(struct_name, expr.method_name)

        # Look up the method function
        if mangled_name not in self.functions:
            raise ValueError(f"Undefined method: {struct_name}.{expr.method_name}")

        method_func = self.functions[mangled_name]

        # Generate arguments: [self, arg1, arg2, ...]
        # Check if method expects mutable self (pointer)
        self_arg = obj_val
        if method_func.args and isinstance(method_func.args[0].type, ir.PointerType):
            # Method expects pointer to self
            # If object is a variable, pass its alloca directly
            if isinstance(expr.object, Identifier) and expr.object.name in self.variables:
                self_arg = self.variables[expr.object.name]
            else:
                # Otherwise create a temporary
                self_alloca = self.builder.alloca(obj_val.type, name="self_temp")
                self.builder.store(obj_val, self_alloca)
                self_arg = self_alloca

        args = [self_arg]  # self is first argument
        # Arguments are Argument objects with .value
        for arg in expr.arguments:
            args.append(self._generate_expression(arg.value))

        # Call the method
        return self.builder.call(method_func, args, name="methodcall")

    def _generate_self_expr(self, expr: SelfExpr):
        """Generate code for 'self' keyword."""
        if "self" not in self.variables:
            raise ValueError("'self' not found in current scope")

        # Load self from its alloca
        return self.builder.load(self.variables["self"], name="self")

    def _generate_enum_init(self, expr: EnumInit):
        """Generate code for enum variant initialization."""
        if expr.enum_name not in self.enum_types:
            raise ValueError(f"Undefined enum: {expr.enum_name}")

        llvm_enum_type, variant_tags, variant_info = self.enum_types[expr.enum_name]
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

        # Create basic blocks for each arm + merge block
        arm_blocks = []
        for arm in expr.arms:
            arm_block = self.builder.append_basic_block(f"match_arm_{arm.variant_name}")
            arm_blocks.append((arm, arm_block))

        merge_block = self.builder.append_basic_block("match_merge")

        # Create switch instruction
        # Default case goes to first arm (we don't have exhaustiveness checking yet)
        switch = self.builder.switch(tag, arm_blocks[0][1])
        for arm, arm_block in arm_blocks:
            # Get enum info to find tag value
            # We need to extract enum name from the matched expression's type
            # This is a bit hacky - we should track this better
            # For now, we'll iterate through enum_types to find matching LLVM type
            enum_name = None
            for name, (llvm_type, _, _) in self.enum_types.items():
                if llvm_type == matched_val.type:
                    enum_name = name
                    break

            if enum_name:
                _, variant_tags, variant_info = self.enum_types[enum_name]
                tag_value = variant_tags[arm.variant_name]
                tag_const = ir.Constant(ir.IntType(32), tag_value)
                switch.add_case(tag_const, arm_block)

        # Generate code for each arm
        arm_results = []
        for arm, arm_block in arm_blocks:
            self.builder.position_at_end(arm_block)

            # Extract and bind associated values if any
            if arm.bindings and not isinstance(matched_val.type, ir.IntType):
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

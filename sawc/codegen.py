"""
Saw Language Code Generator
Generates LLVM IR from the AST using llvmlite.
"""

from llvmlite import ir, binding
from ast_nodes import (
    Program, Function, Block, Statement, Expression,
    LetStatement, AssignStatement, ReturnStatement, ExpressionStatement,
    IntLiteral, FloatLiteral, BoolLiteral, StringLiteral, Identifier,
    BinaryOp, UnaryOp, FunctionCall, IfExpr,
    TupleLiteral, TupleIndex, MemberAccess, StructInit,
    NoneLiteral, ForceUnwrap, NilCoalesce, OptionalChain,
    Struct, StructField,
    SawType, TypeKind
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
            # Look up the struct type
            if saw_type.struct_name is None:
                raise ValueError("Struct type missing name")
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

        # Second pass: declare all functions
        for func in program.functions:
            self._declare_function(func)

        # Third pass: generate function bodies
        for func in program.functions:
            self._generate_function(func)

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

    def _declare_function(self, func: Function):
        param_types = [self._get_llvm_type(p.type) for p in func.parameters]
        return_type = self._get_llvm_type(func.return_type)

        # Main function should return int for proper exit code
        if func.name == "main" and func.return_type.kind == TypeKind.VOID:
            return_type = ir.IntType(32)

        func_type = ir.FunctionType(return_type, param_types)
        llvm_func = ir.Function(self.module, func_type, name=func.name)
        self.functions[func.name] = llvm_func

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
        if stmt.name not in self.variables:
            raise ValueError(f"Undefined variable: {stmt.name}")
        value = self._generate_expression(stmt.value)
        self.builder.store(value, self.variables[stmt.name])

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
            if is_float:
                return self.builder.fcmp_ordered('==', left, right, name="eqtmp")
            return self.builder.icmp_signed('==', left, right, name="eqtmp")

        elif expr.op == '!=':
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
        args = [self._generate_expression(arg) for arg in expr.arguments]
        return self.builder.call(func, args, name="calltmp")

    def _generate_print(self, arguments):
        if not arguments:
            # Print newline
            fmt = self._create_string_constant("\n")
            zero = ir.Constant(ir.IntType(32), 0)
            fmt_ptr = self.builder.gep(fmt, [zero, zero], inbounds=True)
            return self.builder.call(self.printf, [fmt_ptr])

        arg = arguments[0]
        value = self._generate_expression(arg)

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
        """Generate code for member access on structs."""
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

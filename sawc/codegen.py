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
    TupleLiteral, TupleIndex, MemberAccess,
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
        # First pass: declare all functions
        for func in program.functions:
            self._declare_function(func)

        # Second pass: generate function bodies
        for func in program.functions:
            self._generate_function(func)

        return str(self.module)

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
            raise ValueError("Member access not yet implemented (structs not supported)")

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

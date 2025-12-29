"""
Operator code generation for the Saw code generator.

This module provides mixin methods for generating LLVM IR code for binary
and unary operators, including arithmetic, comparison, and logical operators.

Usage:
    class CodeGenerator(OperatorsMixin, ...):
        pass
"""

from llvmlite import ir
from ast_nodes import BinaryOp, UnaryOp, MoveExpr, ReferenceExpr, CastExpr, TypeKind, Identifier, MemberAccess, ArrayIndex, SelfExpr


class OperatorsMixin:
    """Mixin providing operator generation methods for CodeGenerator.

    Methods:
        _generate_binary_op: Generate code for binary operations
        _generate_logical_and: Generate short-circuit && evaluation
        _generate_logical_or: Generate short-circuit || evaluation
        _generate_unary_op: Generate code for unary operations
        _generate_move_expr: Generate code for move expressions
        _generate_cast_expr: Generate code for type casts
    """

    def _generate_binary_op(self, expr: BinaryOp):
        """Generate code for binary operations.

        Handles arithmetic (+, -, *, /, %), comparison (==, !=, <, >, <=, >=),
        and logical (&&, ||) operators.
        """
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
        """Generate code for unary operations (-, not)."""
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

    def _generate_reference_expr(self, expr: ReferenceExpr):
        """Generate code for reference expression: &expr or &var expr.

        Returns a pointer to the referenced value.
        """
        inner_expr = expr.expr

        if isinstance(inner_expr, Identifier):
            # Reference to a variable - return its alloca
            var_name = inner_expr.name
            if var_name not in self.variables:
                raise ValueError(f"Undefined variable: {var_name}")
            return self.variables[var_name]
        elif isinstance(inner_expr, SelfExpr):
            # Reference to self - return self's alloca/pointer
            if "self" not in self.variables:
                raise ValueError("'self' not available in this context")
            return self.variables["self"]
        elif isinstance(inner_expr, MemberAccess):
            # Reference to struct field - get GEP pointer
            return self._get_member_pointer(inner_expr)
        elif isinstance(inner_expr, ArrayIndex):
            # Reference to array element - get GEP pointer
            return self._get_array_element_pointer(inner_expr)
        else:
            # For other expressions, evaluate and store in a temporary
            value = self._generate_expression(inner_expr)
            temp = self.builder.alloca(value.type, name="ref_temp")
            self.builder.store(value, temp)
            return temp

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

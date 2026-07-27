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

    def _emit_panic(self, message: str):
        """Emit a runtime panic: print `message` to stdout, then abort().

        Mirrors the try!/force-unwrap panic machinery (codegen/results.py):
        a private message global, a printf call, abort(), and unreachable to
        terminate the block. The caller must have positioned the builder in the
        block that should panic.
        """
        msg = message if message.endswith("\n") else message + "\n"
        msg += "\0"
        panic_str = ir.Constant(ir.ArrayType(ir.IntType(8), len(msg)),
                                bytearray(msg.encode('utf-8')))
        panic_global = ir.GlobalVariable(self.module, panic_str.type,
                                         name=f".panic_msg.{self.string_counter}")
        self.string_counter += 1
        panic_global.global_constant = True
        panic_global.initializer = panic_str
        panic_global.linkage = 'private'
        panic_ptr = self.builder.bitcast(panic_global, ir.PointerType(ir.IntType(8)))
        self.builder.call(self.printf, [panic_ptr])
        self.builder.call(self.abort, [])
        self.builder.unreachable()

    def _check_divisor_nonzero(self, divisor):
        """Guard an integer division/modulo: panic if `divisor` is zero.

        Emits `if divisor == 0 { panic } else { continue }` and leaves the
        builder positioned in the continue block, where the raw sdiv/srem is
        then generated. Needed because arm64 does not trap on integer
        divide-by-zero, so without this the program silently returns garbage.
        (INT_MIN / -1 overflow is intentionally NOT handled here; integer
        overflow semantics are an open spec question — see todo_jul26.md #5/#7.)
        """
        zero = ir.Constant(divisor.type, 0)
        is_zero = self.builder.icmp_signed('==', divisor, zero, name="divzero_check")
        func = self.builder.function
        panic_bb = func.append_basic_block(name="div_panic")
        cont_bb = func.append_basic_block(name="div_cont")
        self.builder.cbranch(is_zero, panic_bb, cont_bb)

        self.builder.position_at_end(panic_bb)
        self._emit_panic("panic: division by zero")

        self.builder.position_at_end(cont_bb)

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
                # Float division keeps IEEE inf/nan semantics (untouched).
                return self.builder.fdiv(left, right, name="divtmp")
            # Integer division: panic on a zero divisor instead of returning
            # garbage (arm64 does not trap).
            self._check_divisor_nonzero(right)
            return self.builder.sdiv(left, right, name="divtmp")

        elif expr.op == '%':
            # Modulo only works on integers; same zero-divisor panic as /.
            self._check_divisor_nonzero(right)
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
            # Reference to array/pointer element - get a stable GEP pointer
            return self._get_array_element_pointer(inner_expr)
        else:
            # For other expressions, evaluate and store in a temporary
            value = self._generate_expression(inner_expr)
            temp = self._entry_alloca(value.type, name="ref_temp")
            self.builder.store(value, temp)
            return temp

    def _get_array_element_pointer(self, expr: ArrayIndex):
        """Return a stable pointer to an array or pointer element, for `&arr[i]`.

        Mirrors the lvalue logic used by array-element assignment: obtain a
        pointer to the container's storage, then GEP into it -- so the reference
        aliases the real element rather than a materialized copy.
        """
        index_val = self._generate_expression(expr.index)
        container_expr = expr.array_expr

        # Obtain a pointer to the container's storage.
        if isinstance(container_expr, Identifier):
            if container_expr.name not in self.variables:
                raise ValueError(f"Undefined variable: {container_expr.name}")
            container_ptr = self.variables[container_expr.name]
        elif isinstance(container_expr, SelfExpr):
            container_ptr = self.variables["self"]
        elif isinstance(container_expr, MemberAccess):
            container_ptr = self._get_member_pointer(container_expr)
        elif isinstance(container_expr, ArrayIndex):
            container_ptr = self._get_array_element_pointer(container_expr)
        else:
            # Fallback: materialize the container (won't propagate mutations).
            container_val = self._generate_expression(container_expr)
            container_ptr = self._entry_alloca(container_val.type, name="arr_tmp")
            self.builder.store(container_val, container_ptr)

        pointee = container_ptr.type.pointee
        if isinstance(pointee, ir.ArrayType):
            zero = ir.Constant(ir.IntType(64), 0)
            return self.builder.gep(container_ptr, [zero, index_val], name="elem_ptr")
        elif isinstance(pointee, ir.PointerType):
            # The variable holds a pointer value; load it, then offset.
            base = self.builder.load(container_ptr, name="ptr_base")
            return self.builder.gep(base, [index_val], name="ptr_elem")
        else:
            raise ValueError(
                f"Cannot take reference to element of non-array type: {pointee}")

    def _generate_cast_expr(self, expr: CastExpr):
        """Generate code for type cast: expr as Type"""
        value = self._generate_expression(expr.expr)
        from_saw_type = self._expr_type(expr.expr)
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

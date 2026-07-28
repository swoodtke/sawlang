"""
Statement generation for the Saw code generator.

This module provides mixin methods for generating LLVM IR code for statements
including let bindings, assignments, and return statements.

Usage:
    class CodeGenerator(StatementsMixin, ...):
        pass
"""

from llvmlite import ir
from ast_nodes import (
    Statement, LetStatement, AssignStatement, CompoundAssignStatement, ReturnStatement,
    GuardLetStatement, BreakStatement, ContinueStatement, ExpressionStatement,
    WhileExpr, ForLoop, Identifier, MemberAccess, ArrayIndex, SelfExpr,
    MoveExpr, SawType, TypeKind
)


class StatementsMixin:
    """Mixin providing statement generation methods for CodeGenerator.

    Methods:
        _generate_statement: Dispatch to appropriate statement generator
        _generate_let_statement: Generate let binding
        _expr_type: Read a checked expression's type annotation (fail-loud)
        _generate_assign_statement: Generate assignment
        _generate_return_statement: Generate return statement
    """

    def _generate_statement(self, stmt: Statement):
        """Generate code for a statement.

        Each full statement gets its own statement-scoped temporary list (item
        4): owned Deinit-needing values produced mid-statement that no binding
        takes ownership of (a method-call receiver, a discarded call result) are
        registered here and released LIFO once the statement finishes. Loops
        manage their own per-iteration scopes, so they keep the outer context.
        """
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

        saved_temps = self.statement_temps
        self.statement_temps = []
        try:
            visitor(stmt)
            temps = self.statement_temps
            # Release statement temporaries in reverse creation order (LIFO),
            # unless the statement already terminated the block (e.g. `return`,
            # which cleaned up through the scope machinery instead).
            if temps and not self.builder.block.is_terminated:
                for slot, saw_type in reversed(temps):
                    self._emit_drop_at(slot, saw_type)
        finally:
            self.statement_temps = saved_temps

    # ===== Statement Visitor Methods =====

    def visit_LetStatement(self, stmt: LetStatement):
        self._generate_let_statement(stmt)

    def visit_AssignStatement(self, stmt: AssignStatement):
        self._generate_assign_statement(stmt)

    def visit_CompoundAssignStatement(self, stmt: CompoundAssignStatement):
        self._generate_compound_assign_statement(stmt)

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
        value = self._generate_expression(stmt.expression, need_result=False)
        # A top-level owned temporary whose result is discarded (e.g. the final
        # link of a `a().b().c()` chain) is neither bound nor transferred, so it
        # must be released at statement end too. Register it LAST so it drops
        # FIRST (LIFO), before any receiver temporaries it was built from.
        if (self._is_owned_temporary(stmt.expression)
                and not self.builder.block.is_terminated):
            self._register_stmt_temp(value, self._expr_type(stmt.expression))

    def _generate_let_statement(self, stmt: LetStatement):
        """Generate code for a let binding."""
        value = self._generate_expression(stmt.value)

        # Resolve type alias in annotation
        resolved_annotation = self._resolve_type_alias(stmt.type_annotation) if stmt.type_annotation else None

        # Determine the variable type early for copy behavior
        var_type = resolved_annotation if resolved_annotation else self._expr_type(stmt.value)

        # Apply copy behavior for ImplicitCopy types when initializing from an existing value
        # (not for fresh struct/enum construction which doesn't need copying)
        # Skip copy for move expressions - ownership is transferred, not copied
        if var_type and isinstance(stmt.value, Identifier) and not isinstance(stmt.value, MoveExpr):
            value = self._generate_copy(value, var_type)

        # Handle None literal type conversion if assigning to optional with different inner type
        if resolved_annotation and resolved_annotation.kind == TypeKind.OPTIONAL:
            is_already_optional = (isinstance(value.type, ir.LiteralStructType) and
                                   len(value.type.elements) == 2 and
                                   isinstance(value.type.elements[0], ir.IntType) and
                                   value.type.elements[0].width == 1)

            if is_already_optional:
                # Value is optional, but check if it's a None literal with i64 placeholder
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

        alloca = self._entry_alloca(value.type, name=stmt.name)
        self.builder.store(value, alloca)
        self.variables[stmt.name] = alloca

        # Track variable type for resource management
        if var_type:
            self.variable_types[stmt.name] = var_type
            # Track for cleanup if type implements Deinit/ImplicitCopy/NoCopy
            if self.cleanup_stack and self._needs_cleanup(var_type):
                self.cleanup_stack[-1].append((stmt.name, var_type))

    def _expr_type(self, expr) -> SawType:
        """Return the SawType of an expression from its typechecker annotation.

        This is the single accessor codegen uses for expression types. It reads
        ``expr.resolved_type`` (stamped by the typechecker at its
        ``_check_expression`` chokepoint) and, when that type mentions generic
        type parameters, substitutes the current monomorphization bindings.

        It fails *loud*, never silent: an unannotated expression is a compiler
        bug (the typechecker must annotate every expression it checks, and
        codegen-synthesized nodes must set ``resolved_type`` at creation). A
        silent ``None`` here is exactly what previously disabled cleanup
        registration and copy insertion and leaked resources.
        """
        resolved = getattr(expr, 'resolved_type', None)
        if resolved is None:
            node = type(expr).__name__
            line = getattr(expr, 'line', '?')
            column = getattr(expr, 'column', '?')
            raise ValueError(
                f"internal compiler error: expression node `{node}` at "
                f"{line}:{column} reached codegen without a resolved_type; "
                f"the typechecker must annotate every expression before codegen"
            )
        # Substitute generic type parameters using the active monomorphization
        # bindings (empty outside of a specialized generic body).
        if self.type_param_context:
            resolved = resolved.substitute(self.type_param_context)
        return resolved

    def _generate_assign_statement(self, stmt: AssignStatement):
        """Generate code for an assignment statement."""
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

                # Apply copy behavior for ImplicitCopy types
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
                # A &/&var reference parameter's slot holds a POINTER to the
                # struct (e.g. Box**), not the struct itself. Load once to get
                # the actual struct pointer (Box*) so field GEP lands on the
                # caller's value. Without this the pointee is a pointer type and
                # the struct-type lookup below fails.
                var_type = self.variable_types.get(obj_expr.name)
                if var_type is not None and var_type.kind == TypeKind.REFERENCE:
                    struct_ptr = self.builder.load(
                        struct_ptr, name=f"{obj_expr.name}_ref")
            elif isinstance(obj_expr, SelfExpr):
                # self.field = value
                struct_ptr = self.variables["self"]
            elif isinstance(obj_expr, MemberAccess):
                # Nested field target: r.inner.field = value. Resolve a pointer
                # to the intermediate field (which may itself be reached through
                # a reference); _get_member_pointer handles the recursion and
                # reference unwrapping.
                struct_ptr = self._get_member_pointer(obj_expr)
            elif isinstance(obj_expr, ArrayIndex):
                # Array/pointer indexing: arr[i].field = value or ptr[i].field = value
                container_val = self._generate_expression(obj_expr.array_expr)
                index_val = self._generate_expression(obj_expr.index)

                if isinstance(container_val.type, ir.PointerType):
                    # Pointer indexing: ptr[i].field = value
                    struct_ptr = self.builder.gep(container_val, [index_val], name="ptr_idx")
                elif isinstance(container_val.type, ir.ArrayType):
                    # Array indexing - need to allocate, store, and use GEP
                    array_ptr = self._entry_alloca(container_val.type, name="arr_tmp")
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

    def _generate_compound_assign_statement(self, stmt: CompoundAssignStatement):
        """Generate code for a compound assignment statement (+=, -=, *=, /=, %=).

        For regular variables: x += 1 becomes x = x + 1
        For references: y += 1 loads through pointer, computes, stores back
        """
        # `x += y` is `x = x + y`, so it takes the same overflow-checked path as
        # the binary operators (design 31). Signedness comes from the target's
        # annotated type (references and unannotated targets default to signed,
        # which is harmless: only the integer add/sub/mul/div branches consult
        # it, and unsigned targets are reliably annotated).
        signed = self._int_is_signed(stmt.target)

        # Get pointer to target
        if isinstance(stmt.target, Identifier):
            var_name = stmt.target.name
            if var_name not in self.variables:
                raise ValueError(f"Undefined variable: {var_name}")
            target_ptr = self.variables[var_name]

            # Check if this is a reference type - if so, it's already a pointer to the data
            var_type = self.variable_types.get(var_name)
            if var_type and var_type.kind == TypeKind.REFERENCE:
                # For references, the variable holds a pointer to the actual data
                # Load the pointer (which points to the referenced value)
                actual_ptr = self.builder.load(target_ptr, name=f"{var_name}_ref")
                # Load current value through the pointer
                current_val = self.builder.load(actual_ptr, name=f"{var_name}_val")
                # Compute new value
                rhs = self._generate_expression(stmt.value)
                new_val = self._apply_compound_op(stmt.op, current_val, rhs, signed)
                # Store back through the pointer
                self.builder.store(new_val, actual_ptr)
            else:
                # Regular variable - load, compute, store
                current_val = self.builder.load(target_ptr, name=f"{var_name}_val")
                rhs = self._generate_expression(stmt.value)
                new_val = self._apply_compound_op(stmt.op, current_val, rhs, signed)
                self.builder.store(new_val, target_ptr)

        elif isinstance(stmt.target, MemberAccess):
            # Field compound assignment: obj.field += value
            field_ptr = self._get_member_pointer(stmt.target)
            current_val = self.builder.load(field_ptr, name="field_val")
            rhs = self._generate_expression(stmt.value)
            new_val = self._apply_compound_op(stmt.op, current_val, rhs, signed)
            self.builder.store(new_val, field_ptr)

        elif isinstance(stmt.target, ArrayIndex):
            # Array element compound assignment: arr[i] += value
            container_expr = stmt.target.array_expr
            index_val = self._generate_expression(stmt.target.index)

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
                raise ValueError(f"Unsupported container expression in compound assignment: {type(container_expr)}")

            current_val = self.builder.load(elem_ptr, name="elem_val")
            rhs = self._generate_expression(stmt.value)
            new_val = self._apply_compound_op(stmt.op, current_val, rhs, signed)
            self.builder.store(new_val, elem_ptr)

        else:
            raise ValueError(f"Invalid compound assignment target: {type(stmt.target)}")

    def _apply_compound_op(self, op: str, left, right, signed: bool = True):
        """Apply a compound assignment operator and return the result.

        Integer +/-/* are overflow-checked and integer //% are zero-divisor and
        INT_MIN/-1 checked, exactly as the corresponding binary operators
        (design 31) -- `x += y` must not silently wrap where `x = x + y` panics.
        Float ops are untouched.
        """
        is_float = isinstance(left.type, ir.DoubleType)

        if op == '+':
            if is_float:
                return self.builder.fadd(left, right, name="addtmp")
            return self._checked_arith('+', left, right, signed)
        elif op == '-':
            if is_float:
                return self.builder.fsub(left, right, name="subtmp")
            return self._checked_arith('-', left, right, signed)
        elif op == '*':
            if is_float:
                return self.builder.fmul(left, right, name="multmp")
            return self._checked_arith('*', left, right, signed)
        elif op == '/':
            if is_float:
                return self.builder.fdiv(left, right, name="divtmp")
            self._check_divisor_nonzero(right)
            if signed:
                self._check_div_no_overflow(left, right)
            return self.builder.sdiv(left, right, name="divtmp")
        elif op == '%':
            self._check_divisor_nonzero(right)
            if signed:
                self._check_div_no_overflow(left, right)
            return self.builder.srem(left, right, name="modtmp")
        else:
            raise ValueError(f"Unknown compound operator: {op}")

    def _generate_return_statement(self, stmt: ReturnStatement):
        """Generate code for a return statement."""
        # Generate return value first (before cleanup, in case it uses local vars)
        if stmt.value is not None:
            value = self._gen_transfer_value(stmt.value)
        else:
            value = None

        # Drain statement-scoped temporaries produced while evaluating the return
        # expression -- e.g. the `makeR()` receiver in `return makeR().value()`
        # (brief 23 item 3). The end-of-statement drain in `_generate_statement`
        # is skipped once `return` terminates the block, so it must run HERE,
        # before the terminator, in LIFO order. The returned value is exempt: it
        # is never registered as a statement temp (only unbound owned receivers
        # and discarded results are), so it is not released here -- we never free
        # what we return.
        if self.statement_temps:
            for slot, saw_type in reversed(self.statement_temps):
                self._emit_drop_at(slot, saw_type)
            self.statement_temps = []

        # Cleanup all scopes before returning
        self._cleanup_all_scopes()

        # Now return
        if value is not None:
            self.builder.ret(value)
        else:
            # A valueless `return` in a Saw void function. main() is the one such
            # function whose LLVM signature is NOT void: it lowers to i32 for the
            # process exit code. Emitting `ret void` there crashes verification,
            # so match the LLVM return type -- `ret i32 0` for main, mirroring the
            # implicit-fallthrough behavior; `ret void` for every other case.
            ret_type = self.builder.function.function_type.return_type
            if isinstance(ret_type, ir.VoidType):
                self.builder.ret_void()
            else:
                self.builder.ret(ir.Constant(ret_type, 0))

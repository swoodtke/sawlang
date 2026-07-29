"""
Conditional expression handling for the Saw code generator.

This module provides mixin methods for generating code for conditional
expressions including if expressions, if-let optional binding, and
guard-let early exit.

Usage:
    class CodeGenerator(ConditionalsMixin, ...):
        pass
"""

from llvmlite import ir
from ast_nodes import IfExpr, IfLetExpr, GuardLetStatement, TypeKind


class ConditionalsMixin:
    """Mixin providing conditional expression methods for CodeGenerator.

    Methods:
        _generate_if_expression: Generate code for if/else expressions
        _generate_if_let_expression: Generate code for if let optional binding
        _generate_guard_let_statement: Generate code for guard let early exit
    """

    def _generate_if_expression(self, expr: IfExpr):
        """Generate code for if/else expression.

        Handles branch code generation, optional wrapping when branch types
        differ, and phi nodes for merging branch values.
        """
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

        # Case A: both branches yield same-typed values -> phi merge.
        if (then_val is not None and else_val is not None
                and then_val.type == else_val.type):
            if not then_terminated:
                self.builder.position_at_end(then_bb_end)
                self.builder.branch(merge_bb)
            if not else_terminated:
                self.builder.position_at_end(else_bb_end)
                self.builder.branch(merge_bb)
            self.builder.position_at_start(merge_bb)
            phi = self.builder.phi(then_val.type, name="iftmp")
            phi.add_incoming(then_val, then_bb_end)
            phi.add_incoming(else_val, else_bb_end)
            return phi

        # Case B: a no-else (or valueless-else) `if` that still yields a value
        # from its then-branch. The then value is produced inside the then block
        # and does NOT dominate the merge, so returning it directly emits an
        # undominated SSA use (LLVM verify crash) whenever a caller consumes the
        # result -- e.g. this `if` as the tail of an `if let` branch. Route
        # through an entry-block result slot: default-initialise it in entry (so
        # the else/fallthrough path has a defined value), store the then value on
        # the taken path, and load at the merge. Every path stores, so the load
        # dominates. (Mirror of the if-let result-slot idiom below.)
        if (then_val is not None and else_val is None
                and not isinstance(then_val.type, ir.VoidType)):
            result_alloca = self._entry_alloca(then_val.type, name="if_result")
            zero_val = ir.Constant(
                then_val.type,
                0 if isinstance(then_val.type, ir.IntType) else None)
            entry_block = func.entry_basic_block
            if entry_block.terminator is not None:
                self.builder.position_before(entry_block.terminator)
            else:
                self.builder.position_at_end(entry_block)
            self.builder.store(zero_val, result_alloca)

            self.builder.position_at_end(then_bb_end)
            if not then_terminated:
                self.builder.store(then_val, result_alloca)
                self.builder.branch(merge_bb)
            self.builder.position_at_end(else_bb_end)
            if not else_terminated:
                self.builder.branch(merge_bb)
            self.builder.position_at_start(merge_bb)
            return self.builder.load(result_alloca, name="iftmp")

        # Case B-mirror: the then-branch diverges (terminated with no value, e.g.
        # `if cond { panic(...) } else { v }`, design 49) while the else-branch
        # yields a value. Only the else path reaches the merge; route its value
        # through an entry-block slot so the load at the merge dominates (the then
        # path never stores, but it never reaches the merge either).
        if (then_terminated and else_val is not None
                and not isinstance(else_val.type, ir.VoidType)):
            result_alloca = self._entry_alloca(else_val.type, name="if_result")
            zero_val = ir.Constant(
                else_val.type,
                0 if isinstance(else_val.type, ir.IntType) else None)
            entry_block = func.entry_basic_block
            if entry_block.terminator is not None:
                self.builder.position_before(entry_block.terminator)
            else:
                self.builder.position_at_end(entry_block)
            self.builder.store(zero_val, result_alloca)

            self.builder.position_at_end(else_bb_end)
            if not else_terminated:
                self.builder.store(else_val, result_alloca)
                self.builder.branch(merge_bb)
            self.builder.position_at_start(merge_bb)
            return self.builder.load(result_alloca, name="iftmp")

        # Otherwise: no capturable value -> just wire the branches.
        if not then_terminated:
            self.builder.position_at_end(then_bb_end)
            self.builder.branch(merge_bb)
        if not else_terminated:
            self.builder.position_at_end(else_bb_end)
            self.builder.branch(merge_bb)

        # Merge block
        self.builder.position_at_start(merge_bb)

        return then_val

    def _generate_if_let_expression(self, expr: IfLetExpr):
        """Generate code for if let/var optional binding.

        Extracts value from optional if present, binds it to a variable,
        and executes the then branch. Otherwise executes the else branch.
        """
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
        alloca = self._entry_alloca(inner_val.type, name=expr.name)
        self.builder.store(inner_val, alloca)
        self.variables[expr.name] = alloca

        # Store the type of the bound variable for type inference
        # Infer the inner type from the optional expression
        opt_type = self._expr_type(expr.optional_expr)
        if opt_type and opt_type.kind == TypeKind.OPTIONAL and opt_type.inner_type:
            self.variable_types[expr.name] = opt_type.inner_type

        # The if-let binding is released at the end of the then-branch scope (brief
        # 23 item 2), but ONLY when the optional source is a fresh owned temporary:
        # then the unwrapped value is solely owned by this binding. A named/field
        # optional is owned elsewhere (its own cleanup runs), so releasing here
        # would double-free it. When the binding IS owned here, register a runtime
        # drop flag (design 42) BEFORE the branch body so a `move` of the binding
        # inside the branch clears it — otherwise the scope-exit drop would
        # double-free a moved-out value (notably an erased `Box<any T>`, whose
        # second teardown aborts). The flag mirrors regular-local cleanup.
        inner_type = self.variable_types.get(expr.name)
        owns_binding = (inner_type is not None
                        and self._is_owned_temporary(expr.optional_expr)
                        and self._needs_cleanup(inner_type))
        drop_flag = None
        if owns_binding:
            drop_flag = self._entry_alloca(ir.IntType(1), name=f"{expr.name}.dropflag")
            self.builder.store(ir.Constant(ir.IntType(1), 1), drop_flag)
            self.drop_flags[expr.name] = drop_flag

        then_val = self._generate_block(expr.then_branch)

        # Skip if the branch already terminated (return/break cleaned all scopes).
        if owns_binding and not self.builder.block.is_terminated:
            needs = self.builder.load(drop_flag, name=f"{expr.name}.needsdrop")
            drop_bb = self.builder.function.append_basic_block(
                name=f"iflet.drop.{expr.name}")
            cont_bb = self.builder.function.append_basic_block(
                name=f"iflet.drop.{expr.name}.cont")
            self.builder.cbranch(needs, drop_bb, cont_bb)
            self.builder.position_at_start(drop_bb)
            self._emit_drop_at(alloca, inner_type)
            if not self.builder.block.is_terminated:
                self.builder.branch(cont_bb)
            self.builder.position_at_start(cont_bb)

        # Remove the bound variable from scope after the block
        del self.variables[expr.name]
        if expr.name in self.variable_types:
            del self.variable_types[expr.name]
        if drop_flag is not None:
            self.drop_flags.pop(expr.name, None)

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

                # Create alloca for result in the entry block
                result_alloca = self._entry_alloca(optional_type, name="if_let_result")

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

                # Create alloca for result in the entry block
                result_alloca = self._entry_alloca(optional_type, name="if_let_result")

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
            # Create alloca for result in the entry block
            result_alloca = self._entry_alloca(then_val.type, name="if_let_result")

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
            # Create alloca for result in the entry block and initialize to zero
            result_alloca = self._entry_alloca(then_val.type, name="if_let_result")
            # Initialize to zero/null in the entry block so the value dominates the
            # merge-block load in case the else path (which stores nothing) is taken.
            zero_val = ir.Constant(then_val.type, 0 if isinstance(then_val.type, ir.IntType) else None)
            entry_block = func.entry_basic_block
            if entry_block.terminator is not None:
                self.builder.position_before(entry_block.terminator)
            else:
                self.builder.position_at_end(entry_block)
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
        """Generate code for guard let/var optional binding.

        If the optional contains a value, binds it and continues execution.
        Otherwise executes the else branch which must contain an early exit
        (return, break, etc.).
        """
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
        alloca = self._entry_alloca(inner_val.type, name=stmt.name)
        self.builder.store(inner_val, alloca)
        self.variables[stmt.name] = alloca

        # Store the type of the bound variable for type inference
        opt_type = self._expr_type(stmt.optional_expr)
        if opt_type and opt_type.kind == TypeKind.OPTIONAL and opt_type.inner_type:
            self.variable_types[stmt.name] = opt_type.inner_type

        # Register the guard binding for cleanup in the ENCLOSING scope (brief 23
        # item 2). A guard binding deliberately outlives the guard and lives to
        # the end of the surrounding block, so -- unlike an if-let binding -- its
        # cleanup belongs to the enclosing scope, not a guard-local one. Same
        # sole-ownership gate as if-let: only a fresh owned-temporary source makes
        # this binding the sole owner; a named/field optional is cleaned by its
        # own binding, so registering here too would double-free.
        inner_type = self.variable_types.get(stmt.name)
        if (inner_type is not None
                and self._is_owned_temporary(stmt.optional_expr)
                and self._needs_cleanup(inner_type)
                and self.cleanup_stack):
            self.cleanup_stack[-1].append((stmt.name, inner_type))

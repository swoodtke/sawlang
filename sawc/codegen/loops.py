"""
Loop handling for the Saw code generator.

This module provides mixin methods for generating code for loop constructs
including while loops, for loops (using Iterator), and break/continue statements.

Loop representation:
- Loops use basic blocks: condition, body, and end
- Loop stack tracks (continue_block, break_block, result_storage) for nested loops
- For loops desugar to Iterator::next() calls

Usage:
    class CodeGenerator(LoopsMixin, ...):
        pass
"""

from typing import Optional
from llvmlite import ir
from ast_nodes import WhileExpr, ForLoop, RangeExpr, BreakStatement, ContinueStatement, TypeKind


class LoopsMixin:
    """Mixin providing loop generation methods for CodeGenerator.

    Methods:
        _generate_while_expr: Generate while loop (statement context)
        _generate_for_loop: Generate for loop (statement context)
        _find_struct_name_for_value: Find struct name for an LLVM value
        _generate_for_loop_value: Generate for loop (expression context)
        _generate_while_expr_value: Generate while loop (expression context)
        _generate_break_statement: Generate break statement
        _generate_continue_statement: Generate continue statement
    """

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
            iter_alloca, next_func, item_type = self._init_range_iterator(stmt.iterable)
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
            iter_alloca = self._entry_alloca(iter_val.type, name="__iter")
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
        loop_var_alloca = self._entry_alloca(item_type, name=stmt.variable)
        self.builder.store(loop_val, loop_var_alloca)
        self.variables[stmt.variable] = loop_var_alloca

        # An OWNING loop variable (a retained element yielded by a custom
        # iterator, e.g. `for e in set.iter()`) must be RELEASED at the end of
        # each iteration unless the body moved it out (design 65). Register it in
        # a per-iteration cleanup scope with a fresh drop flag (reset each pass),
        # then drop-if-unmoved before branching back to the condition.
        elem_saw = getattr(stmt, 'element_type', None)
        drop_loop_var = (elem_saw is not None
                         and not isinstance(stmt.iterable, RangeExpr)
                         and self._needs_cleanup(elem_saw))
        if drop_loop_var:
            self.variable_types[stmt.variable] = elem_saw
            self.cleanup_stack.append([])
            self._register_cleanup(stmt.variable, elem_saw)

        # Generate body block
        self._generate_block(stmt.body)

        # Release the loop variable (if not moved out) before the back-edge.
        if drop_loop_var and not self.builder.block.is_terminated:
            self._cleanup_scope(self.cleanup_stack.pop())
        elif drop_loop_var:
            self.cleanup_stack.pop()

        # If block doesn't end with terminator, go back to condition
        if not self.builder.block.is_terminated:
            self.builder.branch(cond_block)

        # Pop loop blocks
        self.loop_stack.pop()

        # Clean up loop variable from scope
        del self.variables[stmt.variable]
        if drop_loop_var:
            self.variable_types.pop(stmt.variable, None)
            self.drop_flags.pop(stmt.variable, None)

        # Position at end block for next statements
        self.builder.position_at_end(end_block)

    def _init_range_iterator(self, range_expr: RangeExpr):
        """Materialize the iterator for a `for ... in start..end` / `..=` loop.

        Returns (iter_alloca, next_func, item_type). An exclusive range uses the
        builtin `Range` (`{current, end}`); an inclusive `..=` range uses
        `RangeInclusive` (`{current, last, done}`) whose `next()` latches `done`
        at `last` so `0..=Int.max` never increments past the end (design 53)."""
        start_val = self._generate_expression(range_expr.start)
        end_val = self._generate_expression(range_expr.end)
        if getattr(range_expr, 'is_inclusive', False):
            range_type, _ = self.struct_types["RangeInclusive"]
            iter_alloca = self._entry_alloca(range_type, name="__range_inc")
            range_val = ir.Constant(range_type, ir.Undefined)
            range_val = self.builder.insert_value(range_val, start_val, 0)
            range_val = self.builder.insert_value(range_val, end_val, 1)
            range_val = self.builder.insert_value(
                range_val, ir.Constant(ir.IntType(1), 0), 2)  # done = false
            self.builder.store(range_val, iter_alloca)
            return iter_alloca, self.functions["RangeInclusive_next"], self.int_type
        range_type, _ = self.struct_types["Range"]
        iter_alloca = self._entry_alloca(range_type, name="__range")
        range_val = ir.Constant(range_type, ir.Undefined)
        range_val = self.builder.insert_value(range_val, start_val, 0)
        range_val = self.builder.insert_value(range_val, end_val, 1)
        self.builder.store(range_val, iter_alloca)
        return iter_alloca, self.functions["Range_next"], self.int_type

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
            iter_alloca, next_func, item_type = self._init_range_iterator(expr.iterable)
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
            iter_alloca = self._entry_alloca(iter_val.type, name="__iter")
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
            inner_type = self.int_type
        optional_result_type = ir.LiteralStructType([ir.IntType(1), inner_type])
        result_alloca = self._entry_alloca(optional_result_type, name="for.result")

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
        loop_var_alloca = self._entry_alloca(item_type, name=expr.variable)
        self.builder.store(loop_val, loop_var_alloca)
        self.variables[expr.variable] = loop_var_alloca

        # Release an owning loop variable per iteration unless moved (design 65),
        # mirroring the statement-context for-loop.
        elem_saw = getattr(expr, 'element_type', None)
        drop_loop_var = (elem_saw is not None
                         and not isinstance(expr.iterable, RangeExpr)
                         and self._needs_cleanup(elem_saw))
        if drop_loop_var:
            self.variable_types[expr.variable] = elem_saw
            self.cleanup_stack.append([])
            self._register_cleanup(expr.variable, elem_saw)

        # Generate body block
        self._generate_block(expr.body)

        if drop_loop_var and not self.builder.block.is_terminated:
            self._cleanup_scope(self.cleanup_stack.pop())
        elif drop_loop_var:
            self.cleanup_stack.pop()

        # If block doesn't end with terminator, go back to condition
        if not self.builder.block.is_terminated:
            self.builder.branch(cond_block)

        # Pop loop info
        self.loop_stack.pop()

        # Clean up loop variable from scope
        del self.variables[expr.variable]
        if drop_loop_var:
            self.variable_types.pop(expr.variable, None)
            self.drop_flags.pop(expr.variable, None)

        # Load and return result
        self.builder.position_at_end(end_block)
        return self.builder.load(result_alloca, name="for.value")

    def _generate_while_expr_value(self, expr: WhileExpr):
        """Generate LLVM IR for a while loop that returns a value (expression context).

        Conditional loops return Optional<T>, infinite loops return T directly.
        """
        func = self.builder.function

        is_conditional = expr.condition is not None

        # Get the result type from typechecker annotation
        if expr.result_type is not None:
            if is_conditional and expr.result_type.kind == TypeKind.OPTIONAL:
                # Conditional loop: result_type is Optional<T>, extract inner type
                inner_type = self._get_llvm_type(expr.result_type.inner_type)
            elif is_conditional:
                # Fallback for void result
                inner_type = self.int_type
            else:
                # Infinite loop: result_type is T directly
                inner_type = self._get_llvm_type(expr.result_type)
        else:
            # Fallback if no type annotation
            inner_type = self.int_type

        if is_conditional:
            # Conditional loop returns Optional<T>
            # Optional is { i1 has_value, T value }
            optional_type = ir.LiteralStructType([ir.IntType(1), inner_type])
            result_alloca = self._entry_alloca(optional_type, name="while.result")

            # Initialize to None (has_value = false, value = 0)
            none_value = ir.Constant(optional_type, [ir.Constant(ir.IntType(1), 0), ir.Constant(inner_type, 0)])
            self.builder.store(none_value, result_alloca)
        else:
            # Infinite loop returns T directly
            result_alloca = self._entry_alloca(inner_type, name="while.result")

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
        """Generate LLVM IR for a break statement.

        If the break has a value and the loop is in expression context,
        stores the value for the loop's result.
        """
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
        """Generate LLVM IR for a continue statement.

        Jumps back to the loop condition check.
        """
        if not self.loop_stack:
            raise ValueError("continue outside of loop")

        # Jump to the continue block (condition check)
        continue_block, _, _ = self.loop_stack[-1]
        self.builder.branch(continue_block)

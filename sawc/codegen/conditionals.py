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
from ast_nodes import IfExpr, IfLetExpr, GuardLetStatement, MoveExpr, TypeKind

# Sentinel for "this name had no prior binding" when snapshotting/restoring a
# shadowed enclosing binding across an if-let then-branch (design 100).
_SHADOW_MISSING = object()


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

        # Case A: both branches yield same-typed values -> phi merge. A Void
        # type is NEVER phi-able (LLVM: "void type only allowed for function
        # results"), so a void merge — both branches are void calls, or a void
        # if/else-chain in tail position of a Void-returning fn/closure — must
        # skip the phi and just wire the branches (design 59 C). Falls through to
        # the "Otherwise" wiring below, which yields no consumable value.
        if (then_val is not None and else_val is not None
                and then_val.type == else_val.type
                and not isinstance(then_val.type, ir.VoidType)):
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

        # A Void merge produces no consumable value (a phi would be illegal), so
        # report None — the same "no value" contract the match lowering uses.
        # then_val here is at most a void call instr that must not escape upward.
        if then_val is not None and isinstance(then_val.type, ir.VoidType):
            return None
        return then_val

    def _optional_binding_owns(self, node) -> bool:
        """Whether an `if let` / `guard let` binding OWNS the payload it bound —
        and must therefore release it when its scope ends.

        Three ways the payload becomes the binding's: a `move` scrutinee handed
        the whole optional over, a fresh temporary minted a value nobody else
        holds, or the design-131 place rule retained a second reference out of a
        place the scrutinee keeps. A plain read of a trivial payload owns
        nothing (there is nothing to release), and a non-retained read out of a
        place is still owned by that place — releasing it here would double-free.
        """
        src = node.optional_expr
        return (isinstance(src, MoveExpr)
                or self._is_owned_temporary(src)
                or getattr(node, 'payload_needs_copy', False))

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

        opt_type = self._expr_type(expr.optional_expr)
        inner_saw = (opt_type.inner_type if opt_type and opt_type.kind == TypeKind.OPTIONAL
                     and opt_type.inner_type else None)

        # Design 100: an if-let binding may SHADOW an enclosing binding of the
        # same name (`if let x = x` is the blessed unwrap). Snapshot the shadowed
        # entries now so they can be RESTORED (not deleted) at the end of the
        # then-branch — otherwise the outer binding would vanish from codegen's
        # flat name maps and a later use of it would ICE ("Undefined variable").
        if expr.pattern is not None:
            _shadow_names = self._pattern_binding_names(expr.pattern)
        elif expr.name == "_":
            _shadow_names = []  # design 111 rider: `_` binds nothing
        else:
            _shadow_names = [expr.name]
        _shadow_save = [
            (nm,
             self.variables.get(nm, _SHADOW_MISSING),
             self.variable_types.get(nm, _SHADOW_MISSING),
             self.drop_flags.get(nm, _SHADOW_MISSING))
            for nm in _shadow_names]

        # Tuple pattern (design 63): destructure the unwrapped tuple into its
        # bindings. Ownership of the components stays with the source optional, so
        # the drop-flag machinery below is skipped (bind by value, no release).
        pattern_names = []
        if expr.pattern is not None:
            self._destructure_bind(expr.pattern, inner_val, inner_saw, expr.mutable, False)
            pattern_names = self._pattern_binding_names(expr.pattern)
        elif expr.name == "_":
            # Design 111 rider: `if let _ = opt` binds nothing. Drop the unwrapped
            # payload immediately when this optional is a fresh owned temporary
            # whose payload we now solely hold (a named/field source keeps owning
            # it). This is how a `Void?` is consumed (its unit payload is trivial).
            if (inner_saw is not None
                    and self._is_owned_temporary(expr.optional_expr)
                    and self._needs_cleanup(inner_saw)):
                slot = self._entry_alloca(inner_val.type, name="_.discard")
                self.builder.store(inner_val, slot)
                self._emit_drop_at(slot, inner_saw)
        else:
            # For 'if let', create a copy; for 'if var', we store and use reference
            # Currently, we always create a local variable (copy semantics for if let)
            # For if var reference semantics, we'd need to track the original optional's alloca
            # design 131: out of a PLACE scrutinee the binding is a value read,
            # so it takes its own reference to the payload (the scrutinee keeps
            # its). That makes the binding an owner, which `owns_binding` below
            # picks up so it is released at the end of the then-branch.
            bound_val = self._retain_read_payload(expr, inner_val)
            alloca = self._entry_alloca(bound_val.type, name=expr.name)
            self.builder.store(bound_val, alloca)
            self.variables[expr.name] = alloca

            # Store the type of the bound variable for type inference
            if inner_saw is not None:
                self.variable_types[expr.name] = inner_saw

        # The if-let binding is released at the end of the then-branch scope (brief
        # 23 item 2), but ONLY when the optional source is a fresh owned temporary:
        # then the unwrapped value is solely owned by this binding. A named/field
        # optional is owned elsewhere (its own cleanup runs), so releasing here
        # would double-free it. When the binding IS owned here, register a runtime
        # drop flag (design 42) BEFORE the branch body so a `move` of the binding
        # inside the branch clears it — otherwise the scope-exit drop would
        # double-free a moved-out value (notably an erased `Box<any T>`, whose
        # second teardown aborts). The flag mirrors regular-local cleanup.
        inner_type = self.variable_types.get(expr.name) if expr.pattern is None else None
        owns_binding = (inner_type is not None
                        and self._optional_binding_owns(expr)
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

        # Restore the shadowed enclosing binding(s), or remove the if-let binding
        # if it shadowed nothing (design 100). This replaces the old unconditional
        # delete, which dropped an outer binding of the same name.
        for nm, sv, st, sf in _shadow_save:
            if sv is _SHADOW_MISSING:
                self.variables.pop(nm, None)
            else:
                self.variables[nm] = sv
            if st is _SHADOW_MISSING:
                self.variable_types.pop(nm, None)
            else:
                self.variable_types[nm] = st
            if sf is _SHADOW_MISSING:
                self.drop_flags.pop(nm, None)
            else:
                self.drop_flags[nm] = sf

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

        # A branch that produces only a Void value (e.g. a void call tail like
        # `foo(x)` in `if let x = opt { foo(x) } else { foo(0) }`) yields no
        # consumable result — normalize it to None so the result-capturing logic
        # below never allocas a Void slot (an alloca of a Void type asserts inside
        # llvmlite: "not isinstance(pointee, VoidType)"). Mirrors the Void contract
        # `_generate_if_expression` already enforces (DF7).
        if then_val is not None and isinstance(then_val.type, ir.VoidType):
            then_val = None
        if else_val is not None and isinstance(else_val.type, ir.VoidType):
            else_val = None

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

        opt_type = self._expr_type(stmt.optional_expr)
        inner_saw = (opt_type.inner_type if opt_type and opt_type.kind == TypeKind.OPTIONAL
                     and opt_type.inner_type else None)

        # Tuple pattern (design 63): destructure the unwrapped tuple into its
        # bindings (bind by value; components stay owned by the source optional).
        if stmt.pattern is not None:
            self._destructure_bind(stmt.pattern, inner_val, inner_saw, stmt.mutable, False)
            return

        # Design 111 rider: `guard let _ = opt else { ... }` binds nothing. Drop the
        # unwrapped payload immediately for a fresh owned-temporary source (a
        # named/field source keeps owning it). Consumes a `Void?` (trivial unit).
        if stmt.name == "_":
            if (inner_saw is not None
                    and self._is_owned_temporary(stmt.optional_expr)
                    and self._needs_cleanup(inner_saw)):
                slot = self._entry_alloca(inner_val.type, name="_.discard")
                self.builder.store(inner_val, slot)
                self._emit_drop_at(slot, inner_saw)
            return

        # Store in a local variable. design 131: a place scrutinee makes this a
        # value read, so the binding takes its own reference (see the if-let
        # twin) and becomes an owner in the cleanup registration below.
        bound_val = self._retain_read_payload(stmt, inner_val)
        alloca = self._entry_alloca(bound_val.type, name=stmt.name)
        self.builder.store(bound_val, alloca)
        self.variables[stmt.name] = alloca

        # Store the type of the bound variable for type inference
        if inner_saw is not None:
            self.variable_types[stmt.name] = inner_saw

        # Register the guard binding for cleanup in the ENCLOSING scope (brief 23
        # item 2). A guard binding deliberately outlives the guard and lives to
        # the end of the surrounding block, so -- unlike an if-let binding -- its
        # cleanup belongs to the enclosing scope, not a guard-local one. It owns
        # its payload either because the source was a fresh temporary (which
        # handed the payload over) or because the design-131 place rule retained
        # it here; a non-retained read out of a named/field optional is cleaned
        # by that optional's own binding, so registering it here would
        # double-free.
        inner_type = self.variable_types.get(stmt.name)
        if (inner_type is not None
                and self._optional_binding_owns(stmt)
                and self._needs_cleanup(inner_type)
                and self.cleanup_stack):
            # Capture the guard binding's storage (design 100); flag is None —
            # a guard binding uses the static `moved_variables` skip.
            self.cleanup_stack[-1].append(
                (stmt.name, inner_type, self.variables.get(stmt.name), None))

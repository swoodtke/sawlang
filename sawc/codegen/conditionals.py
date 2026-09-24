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
        # type is never phi-able (LLVM: "void type only allowed for function
        # results"), so a void merge (both branches are void calls, or a void
        # if/else-chain in tail position of a Void-returning fn/closure) must
        # skip the phi and just wire the branches. Falls through to the
        # "Otherwise" wiring below, which yields no consumable value.
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
        # `if cond { panic(...) } else { v }`) while the else-branch
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
        # report None: the same "no value" contract the match lowering uses.
        # then_val here is at most a void call instr that must not escape upward.
        if then_val is not None and isinstance(then_val.type, ir.VoidType):
            return None
        return then_val

    def _optional_binding_owns(self, node) -> bool:
        """Whether an `if let` / `guard let` binding owns the payload it bound,
        and must therefore release it when its scope ends.

        Four ways the payload becomes the binding's: a `move` scrutinee handed
        the whole optional over, a fresh temporary minted a value nobody else
        holds, the place rule retained a second reference out of a place the
        scrutinee keeps (design 131), or the coroutine transform already
        settled the question and said `move`. A plain read of a trivial payload
        owns nothing, and a non-retained read out of a place is still owned by
        that place; releasing it here would double-free.

        The fourth cannot be read off the AST: inside a coroutine body the
        transform rewrites `move opt` into a read of the frame field (a bare
        `self.opt` for a `self_opt`-encoded field) paired with a `__saw_forget`
        that clears the field's drop flag, so no `MoveExpr` remains.
        `frame_move_read`, stamped by `_read_field`, is the transform's answer.
        """
        src = node.optional_expr
        return (self._optional_source_hands_over(src)
                or node.payload_needs_copy)

    def _optional_source_hands_over(self, src) -> bool:
        """Whether an optional-binding scrutinee hands its payload to whatever
        binds it: because it was `move`d (in source, or by the coroutine
        transform's `frame_move_read`), or because it was a fresh temporary
        nobody else holds.

        Split out of `_optional_binding_owns` because the `_` arms need exactly
        this and not the `payload_needs_copy` term: `_` binds nothing, so no
        retain is ever emitted for it, and dropping on the strength of a retain
        that did not happen would double-free. The tuple-pattern arms ask it
        too, as their source-ownership answer.
        """
        return (isinstance(src, MoveExpr)
                or getattr(src, 'frame_move_read', False)
                or self._is_owned_temporary(src))

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

        # An if-let binding may shadow an enclosing binding of the same name
        # (`if let x = x` is the blessed unwrap). Snapshot the shadowed entries
        # now so they can be restored (not deleted) at the end of the
        # then-branch; otherwise the outer binding would vanish from codegen's
        # flat name maps and a later use of it would ICE (design 100).
        if expr.pattern is not None:
            _shadow_names = self._pattern_binding_names(expr.pattern)
        elif expr.name == "_":
            _shadow_names = []  # `_` binds nothing
        else:
            _shadow_names = [expr.name]
        _shadow_save = [
            (nm,
             self.variables.get(nm, _SHADOW_MISSING),
             self.variable_types.get(nm, _SHADOW_MISSING),
             self.drop_flags.get(nm, _SHADOW_MISSING))
            for nm in _shadow_names]

        # The binding's own cleanup scope. An `if let` / `if var` / `while let`
        # / `while var` binding lives for the then-branch and no longer, so the
        # branch gets a cleanup scope of its own, exactly as a `match` arm's
        # payload bindings do. Every binding below registers into it through
        # `_register_cleanup`, and it is released at whichever edge the branch
        # leaves through: the fall-through pops and cleans it, while `return`
        # (`_cleanup_all_scopes`), `break` and `continue` (`_cleanup_to_depth`
        # at the loop's depth) reach it on their own edges because it is on the
        # stack they walk. Pushed before the binding is created so a tuple
        # pattern's leaves land here too, not in the enclosing scope.
        self.cleanup_stack.append([])

        # Tuple pattern: destructure the unwrapped tuple into its bindings,
        # which register into the branch scope pushed above.
        pattern_names = []
        if expr.pattern is not None:
            # The source-ownership answer is the `_` arm's own question (see the
            # `guard let` twin): a scrutinee that keeps its payload lends each
            # leaf rather than handing it over, so every owning leaf retains and
            # a `_` leaf consumes nothing.
            keeps = not self._optional_source_hands_over(expr.optional_expr)
            self._destructure_bind(expr.pattern, inner_val, inner_saw,
                                   expr.mutable, keeps)
            pattern_names = self._pattern_binding_names(expr.pattern)
        elif expr.name == "_":
            # `if let _ = opt` binds nothing. Drop the unwrapped payload
            # immediately when the source handed it over: a fresh owned
            # temporary, or a `move` that retired the whole binding (a
            # named/field source keeps owning it, and dropping there would
            # double-free). This is how a `Void?` is consumed (its unit payload
            # is trivial).
            if (inner_saw is not None
                    and self._optional_source_hands_over(expr.optional_expr)
                    and self._needs_cleanup(inner_saw)):
                slot = self._entry_alloca(inner_val.type, name="_.discard")
                self.builder.store(inner_val, slot)
                self._emit_drop_at(slot, inner_saw)
        else:
            # Both `if let` and `if var` bind a fresh local holding the payload;
            # neither aliases the scrutinee's storage. Out of a place scrutinee
            # the binding is a value read, so it takes its own reference to the
            # payload (the scrutinee keeps its). That makes the binding an
            # owner, which `owns_binding` below picks up so it is released at
            # the end of the then-branch (design 131).
            bound_val = self._retain_read_payload(expr, inner_val)
            alloca = self._entry_alloca(bound_val.type, name=expr.name)
            self.builder.store(bound_val, alloca)
            self.variables[expr.name] = alloca

            # Store the type of the bound variable for type inference
            if inner_saw is not None:
                self.variable_types[expr.name] = inner_saw

        # The if-let binding is released at the end of the then-branch scope,
        # but only when it owns the payload (`_optional_binding_owns`: a moved
        # or fresh-temporary source, or a place-rule retain). A non-retained
        # read of a named/field optional is owned elsewhere (its own cleanup
        # runs), so releasing here would double-free it. When the binding is
        # owned here, register it in the branch scope: `_register_cleanup`
        # gives it the runtime drop flag (design 42) before the branch body, so
        # a `move` of the binding inside the branch clears it and the
        # scope-exit drop does not double-free a moved-out value (notably an
        # erased `Box<any T>`, whose second teardown aborts).
        inner_type = self.variable_types.get(expr.name) if expr.pattern is None else None
        owns_binding = (inner_type is not None
                        and self._optional_binding_owns(expr)
                        and self._needs_cleanup(inner_type))
        if owns_binding:
            self._register_cleanup(expr.name, inner_type)

        then_val = self._generate_block(expr.then_branch)

        # Release the branch scope. A terminated branch emits no fall-through
        # drop: a `return`/`break`/`continue` already ran this scope through
        # `_cleanup_all_scopes` / `_cleanup_to_depth` on its own edge, and a
        # panic ends in `unreachable` with nothing left to drop. Either way
        # only the compile-time stack needs balancing. Popped before the else
        # branch is generated, which sees no binding at all.
        if not self.builder.block.is_terminated:
            self._cleanup_scope(self.cleanup_stack.pop())
        else:
            self.cleanup_stack.pop()

        # Restore the shadowed enclosing binding(s), or remove the if-let binding
        # if it shadowed nothing. An unconditional delete would drop an outer
        # binding of the same name.
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
        # consumable result; normalize it to None so the result-capturing logic
        # below never allocas a Void slot (an alloca of a Void type asserts inside
        # llvmlite). Mirrors the Void contract `_generate_if_expression`
        # enforces.
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

        # Tuple pattern: destructure the unwrapped tuple into its bindings. The
        # source-ownership answer is the one the `_` arm below asks: whether
        # the scrutinee handed its payload over (a `move`, or a fresh temporary
        # nobody else holds) or keeps it (a local, a field, a place read). Over
        # a scrutinee that keeps its payload each owning leaf must retain, or
        # its scope exit releases references the scrutinee still owns.
        if stmt.pattern is not None:
            keeps = not self._optional_source_hands_over(stmt.optional_expr)
            self._destructure_bind(stmt.pattern, inner_val, inner_saw,
                                   stmt.mutable, keeps)
            return

        # `guard let _ = opt else { ... }` binds nothing. Drop the
        # unwrapped payload immediately when the source handed it over: a fresh
        # owned temporary or a `move` (a named/field source keeps owning it).
        # Consumes a `Void?` (trivial unit).
        if stmt.name == "_":
            if (inner_saw is not None
                    and self._optional_source_hands_over(stmt.optional_expr)
                    and self._needs_cleanup(inner_saw)):
                slot = self._entry_alloca(inner_val.type, name="_.discard")
                self.builder.store(inner_val, slot)
                self._emit_drop_at(slot, inner_saw)
            return

        # Store in a local variable. A place scrutinee makes this a value read,
        # so the binding takes its own reference (see the if-let twin) and
        # becomes an owner in the cleanup registration below (design 131).
        bound_val = self._retain_read_payload(stmt, inner_val)
        alloca = self._entry_alloca(bound_val.type, name=stmt.name)
        self.builder.store(bound_val, alloca)
        self.variables[stmt.name] = alloca

        # Store the type of the bound variable for type inference
        if inner_saw is not None:
            self.variable_types[stmt.name] = inner_saw

        # Register the guard binding for cleanup in the enclosing scope. A
        # guard binding deliberately outlives the guard and lives to the end of
        # the surrounding block, so, unlike an if-let binding, its cleanup
        # belongs to the enclosing scope. It owns its payload when the source
        # handed it over (a `move` or a fresh temporary) or the place rule
        # retained it here; a non-retained read out of a named/field optional
        # is cleaned by that optional's own binding, so registering it here
        # would double-free.
        inner_type = self.variable_types.get(stmt.name)
        if (inner_type is not None
                and self._optional_binding_owns(stmt)
                and self._needs_cleanup(inner_type)
                and self.cleanup_stack):
            # Capture the guard binding's storage (design 100); flag is None —
            # a guard binding uses the static `moved_variables` skip.
            self.cleanup_stack[-1].append(
                (stmt.name, inner_type, self.variables.get(stmt.name), None))

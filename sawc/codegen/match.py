"""
Match expression generation for the Saw code generator.

This module provides mixin methods for generating LLVM IR code for match
expressions on enum types.

Usage:
    class CodeGenerator(MatchMixin, ...):
        pass
"""

from llvmlite import ir
from ast_nodes import MatchExpr, Block, Identifier
from .mangle import mangle_named


class MatchMixin:
    """Mixin providing match expression generation for CodeGenerator.

    Methods:
        _generate_match_expr: Generate code for match expressions
    """

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

        # Get enum name from typechecker annotation, or fall back to LLVM type matching
        matched_enum_type = getattr(expr, 'matched_enum_type', None)
        if matched_enum_type is not None:
            # Substitute the active monomorphization's type params first, so a
            # match on a generic enum inside a generic body (e.g.
            # `HashSlot<K, V>` in HashMap's methods, design 48) resolves to the
            # concrete registered name rather than `HashSlot$2$K$V`.
            if self.type_param_context:
                matched_enum_type = matched_enum_type.substitute(self.type_param_context)
            # Canonical mangled name for a (possibly generic) enum, matching the
            # name under which it was registered (see codegen/mangle.py).
            enum_name = mangle_named(matched_enum_type.enum_name, matched_enum_type.type_args)
        else:
            enum_name = None
        # Fallback: find the enum name by matching LLVM types (also covers a
        # substitution that did not land on a registered name).
        if enum_name is None or enum_name not in self.enum_types:
            enum_name = None
            for name, (llvm_type, _, _) in self.enum_types.items():
                if llvm_type == matched_val.type:
                    enum_name = name
                    break

        # Ownership model for an OWNED enum scrutinee (design 61, L14/L15).
        #
        # When the matched enum has variants carrying owning (cleanup-needing)
        # payload, a `match owned_value { case V(a, b) -> ... }` CONSUMES the
        # scrutinee: the payload's ownership passes to the arm's bindings. Each
        # owning binding is registered for arm-scope cleanup, so a binding that
        # is not `move`d out is dropped exactly once when the arm ends, and a
        # `move`d one clears its drop flag (the normal conditional-move path) so
        # ownership leaves cleanly. The scrutinee itself is then NOT dropped (its
        # payload is gone), which is what makes Map/Set remove/overwrite/grow —
        # all of which move a slot out and destructure it — release each value
        # exactly once instead of double-freeing (scrutinee drop + moved copy).
        #
        # Gated to owning enums so payload-free / trivial enums (Ordering, the
        # coroutine `__state`, Result<Int,Int>, ...) are completely unaffected.
        variant_cleanup_info = {}
        if enum_name and enum_name in self.enum_types:
            variant_cleanup_info = self.enum_types[enum_name][2]
        enum_has_owning = any(
            any(self._needs_cleanup(ft) for _, ft in flds)
            for flds in variant_cleanup_info.values()
        )
        # The scrutinee is consumable only when it is an owned binding in scope
        # (a `let`/param/if-let local). A field/temporary/borrow is left alone.
        consume_name = None
        if (enum_has_owning and isinstance(expr.matched_expr, Identifier)
                and expr.matched_expr.name in self.variables):
            consume_name = expr.matched_expr.name
        if consume_name is not None:
            # Suppress the scrutinee's own drop on every path: its payload is
            # handed to the arm bindings. Clear a runtime drop flag if present
            # (conditional-move machinery) and mark it moved for the flat skip.
            flag = self.drop_flags.get(consume_name)
            if flag is not None:
                self.builder.store(ir.Constant(ir.IntType(1), 0), flag)
            self.moved_variables.add(consume_name)

        # Create basic blocks for each arm + merge block
        arm_blocks = []
        wildcard_block = None
        for arm in expr.arms:
            arm_block = self.builder.append_basic_block(f"match_arm_{arm.variant_name}")
            arm_blocks.append((arm, arm_block))
            if arm.variant_name == "_":
                wildcard_block = arm_block

        merge_block = self.builder.append_basic_block("match_merge")

        # Create switch instruction
        # Use wildcard as default if present, otherwise first arm
        default_block = wildcard_block if wildcard_block else arm_blocks[0][1]
        switch = self.builder.switch(tag, default_block)

        # Add cases for non-wildcard arms
        if enum_name:
            _, variant_tags, variant_info = self.enum_types[enum_name]
            for arm, arm_block in arm_blocks:
                # Skip wildcard - it's the default case
                if arm.variant_name == "_":
                    continue
                tag_value = variant_tags[arm.variant_name]
                tag_const = ir.Constant(ir.IntType(32), tag_value)
                switch.add_case(tag_const, arm_block)

        # Generate code for each arm
        arm_results = []
        # A Void match (every reaching arm is a void call / void block) must NOT
        # build a phi (design 59 C). Void arms below are replaced with an i32
        # placeholder so a value-match phi stays well-formed; this flag records
        # whether ANY arm actually produced a real (non-void) value, so a purely
        # void match returns None instead of an i32 phi over placeholders.
        match_produces_value = False
        for arm, arm_block in arm_blocks:
            self.builder.position_at_end(arm_block)

            # When we take ownership of an owning scrutinee's payload (consume
            # mode), each owning binding is registered into a per-arm cleanup
            # scope so an un-`move`d binding drops exactly once at arm end and an
            # early `return`/`break` cleans it via `_cleanup_all_scopes`.
            arm_scope_pushed = False
            owning_bindings = []

            # Extract and bind associated values if any (not for wildcard)
            if arm.variant_name != "_" and arm.bindings and not isinstance(matched_val.type, ir.IntType):
                # Get variant info and enum type
                llvm_enum_type, _, variant_info = self.enum_types[enum_name]
                variant_params = variant_info[arm.variant_name]

                # Extract payload
                payload_bytes = self.builder.extract_value(matched_val, 1, name="payload")

                # Cast to appropriate struct type
                param_types = [self._get_llvm_type(t) for _, t in variant_params]
                param_struct_type = ir.LiteralStructType(param_types)

                # Store bytes to memory, then load as struct
                payload_alloca = self._entry_alloca(llvm_enum_type.elements[1], name="payload_alloca")
                self.builder.store(payload_bytes, payload_alloca)
                struct_ptr = self.builder.bitcast(payload_alloca,
                                                  ir.PointerType(param_struct_type),
                                                  name="param_struct_ptr")

                if consume_name is not None:
                    self.cleanup_stack.append([])
                    arm_scope_pushed = True

                # Create variables for bindings
                for i, binding_name in enumerate(arm.bindings):
                    # Extract field from struct
                    field_ptr = self.builder.gep(struct_ptr,
                                                [ir.Constant(ir.IntType(32), 0),
                                                 ir.Constant(ir.IntType(32), i)],
                                                inbounds=True)
                    field_val = self.builder.load(field_ptr, name=binding_name)

                    # Store in a variable
                    var_alloca = self._entry_alloca(field_val.type, name=binding_name)
                    self.builder.store(field_val, var_alloca)
                    self.variables[binding_name] = var_alloca

                    # In consume mode the binding OWNS its payload field: register
                    # cleanup-needing bindings so they drop once at arm end unless
                    # `move`d out (which clears the drop flag). The scrutinee's own
                    # drop was already suppressed above. A `_` discard binding is
                    # NOT registered: it names no value to own, so an owning field
                    # matched `_` is simply not dropped here (used by the Map probe
                    # helpers to inspect a by-value, non-retained slot copy without
                    # releasing its live payload).
                    if arm_scope_pushed and binding_name != "_" and i < len(variant_params):
                        btype = variant_params[i][1]
                        if self._needs_cleanup(btype):
                            self.variable_types[binding_name] = btype
                            self._register_cleanup(binding_name, btype)
                            owning_bindings.append(binding_name)

            # Generate arm body
            if isinstance(arm.body, Block):
                arm_result = self._generate_block(arm.body)
                # Get the value from the block
                if arm_result is None:
                    # Block didn't have a value, use void or a placeholder
                    arm_result = ir.Constant(ir.IntType(32), 0)  # Placeholder
                elif isinstance(arm_result.type, ir.VoidType):
                    # Void function call - use placeholder instead
                    arm_result = ir.Constant(ir.IntType(32), 0)  # Placeholder
                else:
                    match_produces_value = True
            else:
                arm_result = self._generate_expression(arm.body)
                if arm_result is None or isinstance(arm_result.type, ir.VoidType):
                    # No value (e.g. a diverging `panic(...)` arm, design 49) or a
                    # Void expression — use a placeholder. A diverging arm has
                    # already terminated its block with `unreachable`, so this
                    # placeholder is never added to the phi below.
                    arm_result = ir.Constant(ir.IntType(32), 0)  # Placeholder
                else:
                    match_produces_value = True

            # Drop the arm's owning bindings (consume mode): an un-`move`d binding
            # is released here, exactly once. A terminated arm (return/break)
            # already ran `_cleanup_all_scopes` over this scope, so just balance
            # the stack. Done BEFORE reading the arm result into the phi so the
            # cleanup precedes the branch.
            if arm_scope_pushed:
                if not self.builder.block.is_terminated:
                    scope_vars = self.cleanup_stack.pop()
                    self._cleanup_scope(scope_vars)
                else:
                    self.cleanup_stack.pop()

            # Only add to arm_results if block is not terminated (has a return)
            if not self.builder.block.is_terminated:
                arm_results.append((arm_result, self.builder.block))

            # Clean up bindings
            for binding_name in arm.bindings:
                if binding_name in self.variables:
                    del self.variables[binding_name]
            for binding_name in owning_bindings:
                self.variable_types.pop(binding_name, None)
                self.drop_flags.pop(binding_name, None)

            # Branch to merge block (only if block not already terminated)
            if not self.builder.block.is_terminated:
                self.builder.branch(merge_block)

        # Position at merge block
        self.builder.position_at_end(merge_block)

        # Create phi node to merge results. A purely void match (no arm produced
        # a real value — the arm_results hold only i32 placeholders) yields no
        # consumable value and must NOT build a phi (design 59 C).
        if arm_results and match_produces_value:
            result_type = arm_results[0][0].type
            phi = self.builder.phi(result_type, name="match_result")
            for val, block in arm_results:
                phi.add_incoming(val, block)
            return phi
        else:
            # Match doesn't produce a value
            return None

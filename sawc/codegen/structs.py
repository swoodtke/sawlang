"""
Struct expression generation for the Saw code generator.

This module provides mixin methods for generating LLVM IR code for struct
initialization and member access expressions.

Usage:
    class CodeGenerator(StructsMixin, ...):
        pass
"""

from llvmlite import ir
from ast_nodes import (StructInit, FunctionCall, MethodCall, MemberAccess,
                       Identifier, MoveExpr, NoneLiteral, ForceUnwrap, EnumInit,
                       TypeKind, SelfExpr, ArrayIndex, ArrayLiteral, OptionalWrap,
                       ResultOkWrap, ResultErrWrap, carry_retain_stamps)
from const_eval import INT_LIMIT_SPECS


class StructsMixin:
    """Mixin providing struct generation methods for CodeGenerator.

    Methods:
        _generate_struct_init: Generate code for struct initialization
        _generate_member_access: Generate code for member access
    """

    def _generate_struct_init(self, expr: StructInit):
        """Expression visitor entry; no caller-supplied destination."""
        return self._materialize_struct_init(expr, None)

    def _as_memberwise_struct_init(self, expr):
        """Return the checked memberwise construction represented by `expr`.

        Named bare construction parses as `StructInit`.  Empty bare construction
        and module-qualified construction retain call-shaped AST nodes until
        codegen, so destination routing must read their typechecker decisions
        before `calls.py` performs the same conversion on the SSA path.
        """
        if isinstance(expr, (OptionalWrap, ResultOkWrap, ResultErrWrap)):
            return self._as_memberwise_struct_init(expr.value)
        if isinstance(expr, StructInit):
            if (expr.as_function_call is None
                    and expr.resolved_init_params is None):
                return expr
            return None

        if isinstance(expr, FunctionCall):
            resolved_symbol = getattr(expr, "resolved_symbol", None)
            if (resolved_symbol in self.functions
                    or resolved_symbol in self.generic_functions):
                return None
            struct_name = expr.resolved_type_identity or expr.name
            if (struct_name not in self.struct_types
                    and struct_name not in self.generic_structs):
                return None
            if expr.resolved_init_params is not None:
                return None
            field_inits = expr.resolved_field_inits
            if field_inits is None:
                return None
            literal = StructInit(
                struct_name=struct_name,
                field_inits=list(field_inits),
                type_args=expr.type_args,
                line=expr.line,
                column=expr.column,
            )
        elif isinstance(expr, MethodCall):
            field_inits = expr.resolved_field_inits
            if (field_inits is None
                    or expr.resolved_init_params is not None):
                return None
            struct_name = expr.resolved_type_identity
            if struct_name is None:
                raise ValueError(
                    "memberwise module constructor has no resolved identity")
            resolved = getattr(expr, "resolved_type", None)
            type_args = list(resolved.type_args) if (
                resolved is not None and resolved.type_args) else None
            literal = StructInit(
                struct_name=struct_name,
                field_inits=list(field_inits),
                type_args=type_args,
                line=expr.line,
                column=expr.column,
            )
        else:
            return None

        literal.resolved_type = getattr(expr, "resolved_type", None)
        literal.resolved_type_identity = getattr(
            expr, "resolved_type_identity", None)
        literal.autowrap_to_optional = expr.autowrap_to_optional
        literal.autowrap_to_result = expr.autowrap_to_result
        literal.autowrap_result_err = expr.autowrap_result_err
        literal.expected_type = expr.expected_type
        carry_retain_stamps(expr, literal)
        literal.closure_lend = expr.closure_lend
        literal.materialize_for_transfer = getattr(
            expr, "materialize_for_transfer", False)
        return literal

    def _can_materialize_struct_init(self, expr) -> bool:
        """Whether `expr` is a checked memberwise construction."""
        return self._as_memberwise_struct_init(expr) is not None

    def _struct_init_info(self, expr):
        """Resolve a memberwise literal's concrete LLVM layout and field types."""
        materialized = self._as_memberwise_struct_init(expr)
        if materialized is not None:
            expr = materialized
        struct_name = expr.struct_name
        if expr.type_args:
            resolved_type_args = [
                t.substitute(self.type_param_context)
                if self.type_param_context else t
                for t in expr.type_args
            ]
            struct_name = self._ensure_monomorphized_struct(
                expr.struct_name, resolved_type_args)
        elif struct_name in self.generic_structs:
            filled = self._fill_default_type_args(struct_name, [])
            if filled:
                struct_name = self._ensure_monomorphized_struct(
                    expr.struct_name, filled)
        if struct_name not in self.struct_types:
            raise ValueError(f"Undefined struct: {struct_name}")
        llvm_struct_type, field_order = self.struct_types[struct_name]
        field_types = {
            name: self._struct_field_saw_type(struct_name, name)
            for name in field_order
        }
        return struct_name, llvm_struct_type, field_order, field_types

    def _generate_custom_struct_init(self, expr, struct_name):
        """Emit a real `init` call; it is never reinterpreted as field stores."""
        mangled_name = self._mangle_method_name(
            struct_name, "init", expr.resolved_init_params)
        init_func = self.functions[mangled_name]
        param_to_value = {
            param_name: value for param_name, value in expr.field_inits
        }
        args = [
            self._gen_transfer_value(param_to_value[param_name])
            for param_name in expr.resolved_init_params
        ]
        return self.builder.call(init_func, args)

    def _prepare_struct_field_value(self, value_expr, field_type,
                                    expected_llvm_type):
        """Generate one field through the existing copy/coercion/wrap rules."""
        value = self._generate_expression(value_expr)
        if value is None and self.builder.block.is_terminated:
            return None

        if field_type is not None:
            value = self._coerce_int_to_field(value, field_type, value_expr)
        if (field_type is not None
                and self._needs_copy_for_struct_init(value_expr, field_type)):
            # The destination may be opt-encoded while the generated value is
            # its bare payload.  Copy against the payload before wrapping.
            value = self._generate_copy_for_dest(value, field_type)
        if getattr(value_expr, 'autowrap_to_result', None) is not None:
            value = self._maybe_autowrap_optional(value_expr, value)
        fitted = self._fit_optional_slot(value, expected_llvm_type)
        return self._mark_direct_move_source(
            fitted, value_expr, expected_llvm_type)

    def _mark_direct_move_source(self, value, value_expr, expected_llvm_type):
        """Carry a moved local's storage pointer across its drop-flag store."""
        if (isinstance(value_expr, MoveExpr)
                and value_expr.path is None
                and not value_expr.unwrap):
            source = self.variables.get(value_expr.variable)
            if (source is not None
                    and source.type == expected_llvm_type.as_pointer()):
                value.saw_materialized_source = source
        return value

    def _materialize_present_optional_field(self, value_expr, field_ptr,
                                            expected_llvm_type):
        """Store a transform-proven present frame field without an SSA wrapper."""
        optional_type = expected_llvm_type
        optional_ptr = field_ptr
        zero = ir.Constant(ir.IntType(32), 0)
        is_slot_wrapper = (
            isinstance(expected_llvm_type, ir.IdentifiedStructType)
            and len(expected_llvm_type.elements) == 1
        )
        if is_slot_wrapper:
            optional_type = expected_llvm_type.elements[0]
            optional_ptr = self.builder.gep(
                field_ptr, [zero, zero], inbounds=True,
                name="present.slot.value")
        if (not isinstance(optional_type, ir.LiteralStructType)
                or len(optional_type.elements) != 2
                or optional_type.elements[0] != ir.IntType(1)):
            raise ValueError(
                f"invalid proven-present frame field initializer: "
                f"{expected_llvm_type}")
        if is_slot_wrapper:
            if (not isinstance(value_expr, MethodCall)
                    or value_expr.method_name != "of"
                    or len(value_expr.arguments) != 1):
                raise ValueError(
                    "invalid proven-present frame Slot initializer")
            payload_expr = value_expr.arguments[0].value
        else:
            # Legacy opt stores its occupancy Optional directly.  The second
            # check may express that one added layer structurally; consume only
            # the wrap whose target is this exact frame field, leaving any
            # Optional/Result wrappers inside the declared payload intact.
            if (isinstance(value_expr, OptionalWrap)
                    and value_expr.target_type is not None
                    and self._get_llvm_type(
                        value_expr.target_type) == expected_llvm_type):
                payload_expr = value_expr.value
            else:
                payload_expr = value_expr
        payload_type = optional_type.elements[1]
        apply_optional_wrap = True
        if not is_slot_wrapper:
            marked_optional = getattr(
                payload_expr, "autowrap_to_optional", None)
            marked_result = getattr(payload_expr, "autowrap_to_result", None)
            optional_target = (
                self._get_llvm_type(marked_optional)
                if marked_optional is not None else None)
            result_target = (
                self._get_llvm_type(marked_result)
                if marked_result is not None else None)
            # A legacy opt field's outer Optional is frame occupancy and is
            # written below.  An Optional nested inside the actual payload
            # (directly or inside Result) remains a semantic conversion.
            apply_optional_wrap = (
                optional_target == payload_type
                or result_target == payload_type
            )
        tag_ptr = self.builder.gep(
            optional_ptr, [zero, zero], inbounds=True,
            name="present.tag.init")
        payload_ptr = self.builder.gep(
            optional_ptr, [zero, ir.Constant(ir.IntType(32), 1)],
            inbounds=True, name="present.payload.init")
        if self._materialize_wrapped_struct_init(
                payload_expr, payload_ptr,
                apply_optional_wrap=apply_optional_wrap):
            if not self.builder.block.is_terminated:
                self.builder.store(ir.Constant(ir.IntType(1), 1), tag_ptr)
            return
        payload = self._gen_transfer_value(
            payload_expr, apply_optional_wrap=apply_optional_wrap)
        if payload is None and self.builder.block.is_terminated:
            return
        payload = self._mark_direct_move_source(
            payload, payload_expr, payload_type)
        self._store_materialized_or_transfer(
            payload, payload_ptr, final_use=True)
        self.builder.store(ir.Constant(ir.IntType(1), 1), tag_ptr)

    def _emit_zero_fill(self, dest_ptr, llvm_type):
        """Zero every byte of a newly-materialized aggregate destination."""
        size = self._abi_size(llvm_type)
        if size == 0:
            return
        i8 = ir.IntType(8)
        i8ptr = i8.as_pointer()
        memset = self.module.declare_intrinsic(
            "llvm.memset", [i8ptr, self.int_type])
        raw = self.builder.bitcast(dest_ptr, i8ptr, name="zero_dst")
        self.builder.call(memset, [
            raw,
            ir.Constant(i8, 0),
            ir.Constant(self.int_type, size),
            ir.Constant(ir.IntType(1), 0),
        ])

    def _materialize_struct_value(self, expr, name="struct.init",
                                  *, apply_optional_wrap=True):
        """Build a memberwise literal and any transfer wrappers in memory."""
        materialized = self._as_memberwise_struct_init(expr)
        if materialized is None:
            raise ValueError("only memberwise struct construction can be staged")
        _, struct_type, _, _ = self._struct_init_info(materialized)
        outer_saw = None
        if isinstance(expr, OptionalWrap):
            outer_saw = expr.target_type
        elif isinstance(expr, (ResultOkWrap, ResultErrWrap)):
            outer_saw = expr.result_type
        else:
            outer_saw = (
                materialized.autowrap_to_result
                or (materialized.autowrap_to_optional
                    if apply_optional_wrap else None))
        value_type = (self._get_llvm_type(outer_saw)
                      if outer_saw is not None else struct_type)
        slot = self._entry_alloca(value_type, name=name)
        if not self._materialize_wrapped_struct_init(
                expr, slot, apply_optional_wrap=apply_optional_wrap):
            raise ValueError("struct transfer wrapper has incompatible layout")
        if self.builder.block.is_terminated:
            return None
        value = self.builder.load(slot, name=f"{name}.value")
        value.saw_materialized_source = slot
        return value

    def _discard_unused_materialized_load(self, value):
        """Erase a staged aggregate load after its source pointer was consumed."""
        if (not isinstance(value, ir.LoadInstr)
                or getattr(value, "saw_materialized_source", None) is None):
            return
        used = any(
            operand is value
            for block in self.builder.function.blocks
            for instruction in block.instructions
            if instruction is not value
            for operand in instruction.operands
        ) or any(
            incoming is value
            for block in self.builder.function.blocks
            for instruction in block.instructions
            if isinstance(instruction, ir.PhiInstr)
            for incoming, _ in instruction.incomings
        )
        if not used:
            if value.parent is self.builder.block:
                self.builder.remove(value)
            else:
                value.parent.instructions.remove(value)

    def _store_materialized_or_transfer(
            self, value, dest_ptr, *, final_use=False):
        """Move a staged aggregate without recreating an aggregate store.

        ``final_use`` is an explicit codegen-liveness promise: this helper may
        erase the otherwise dead staging load only after its last caller-side
        use has been emitted.
        """
        source = getattr(value, "saw_materialized_source", None)
        if (source is not None
                and source is not dest_ptr
                and source.type == dest_ptr.type):
            self._emit_aggregate_memcpy(
                dest_ptr, source, dest_ptr.type.pointee)
            if final_use:
                self._discard_unused_materialized_load(value)
            return
        self._store_transfer(value, dest_ptr)

    def _store_none_optional_tag(self, value_expr, dest_ptr):
        """Store semantic Optional/Slot absence without touching its payload."""
        llvm_type = dest_ptr.type.pointee
        if (not isinstance(value_expr, NoneLiteral)
                or not isinstance(llvm_type, ir.LiteralStructType)
                or len(llvm_type.elements) != 2
                or llvm_type.elements[0] != ir.IntType(1)):
            return False
        zero = ir.Constant(ir.IntType(32), 0)
        tag_ptr = self.builder.gep(
            dest_ptr, [zero, zero], inbounds=True, name="none.tag")
        self.builder.store(ir.Constant(ir.IntType(1), 0), tag_ptr)
        return True

    def _store_present_optional_value(self, value, dest_ptr):
        """Store a staged payload through Optional layers without SSA wrappers."""
        source = getattr(value, "saw_materialized_source", None)
        if source is None or source.type != value.type.as_pointer():
            return False
        optional_type = dest_ptr.type.pointee
        optional_ptr = dest_ptr
        zero = ir.Constant(ir.IntType(32), 0)
        if (isinstance(optional_type, ir.IdentifiedStructType)
                and len(optional_type.elements) == 1):
            optional_ptr = self.builder.gep(
                dest_ptr, [zero, zero], inbounds=True,
                name="present.slot.value")
            optional_type = optional_type.elements[0]
        tag_ptrs = []
        while (isinstance(optional_type, ir.LiteralStructType)
               and len(optional_type.elements) == 2
               and optional_type.elements[0] == ir.IntType(1)):
            tag_ptrs.append(self.builder.gep(
                optional_ptr, [zero, zero], inbounds=True,
                name="present.tag"))
            payload_ptr = self.builder.gep(
                optional_ptr, [zero, ir.Constant(ir.IntType(32), 1)],
                inbounds=True, name="present.payload")
            payload_type = optional_type.elements[1]
            if payload_type == value.type:
                for tag_ptr in tag_ptrs:
                    self.builder.store(ir.Constant(ir.IntType(1), 1), tag_ptr)
                self._emit_aggregate_memcpy(
                    payload_ptr, source, value.type)
                # The helper consumes `value` completely on its success path.
                self._discard_unused_materialized_load(value)
                return True
            optional_ptr = payload_ptr
            optional_type = payload_type
        return False

    def _materialize_wrapped_struct_init(
            self, expr, dest_ptr, *, already_zeroed=False,
            apply_optional_wrap=True):
        """Build a memberwise struct through its checked Optional/Result wraps."""
        wrappers = []
        inner_expr = expr
        while isinstance(
                inner_expr, (OptionalWrap, ResultOkWrap, ResultErrWrap)):
            if isinstance(inner_expr, OptionalWrap):
                wrappers.append(("optional", inner_expr.target_type, False))
            elif isinstance(inner_expr, ResultErrWrap):
                wrappers.append(("result", inner_expr.result_type, True))
            else:
                wrappers.append(("result", inner_expr.result_type, False))
            inner_expr = inner_expr.value

        literal = self._as_memberwise_struct_init(inner_expr)
        if literal is None:
            return False
        _, struct_type, _, _ = self._struct_init_info(literal)
        if not wrappers:
            result_saw = literal.autowrap_to_result
            optional_saw = (
                literal.autowrap_to_optional if apply_optional_wrap else None)
            if result_saw is not None:
                wrappers.append((
                    "result", result_saw, literal.autowrap_result_err))
            if optional_saw is not None:
                wrappers.append(("optional", optional_saw, False))

        final_type = (
            self._get_llvm_type(wrappers[0][1])
            if wrappers else struct_type)
        destination_optional = False
        if not wrappers and dest_ptr.type.pointee != struct_type:
            probe = dest_ptr.type.pointee
            while (isinstance(probe, ir.LiteralStructType)
                   and len(probe.elements) == 2
                   and probe.elements[0] == ir.IntType(1)):
                probe = probe.elements[1]
            if probe == struct_type:
                final_type = dest_ptr.type.pointee
                destination_optional = True
        if dest_ptr.type.pointee != final_type:
            return False

        target_ptr = dest_ptr
        zero = ir.Constant(ir.IntType(32), 0)
        tag_commits = []
        for index, (kind, saw_type, is_err) in enumerate(wrappers):
            inner_type = (
                self._get_llvm_type(wrappers[index + 1][1])
                if index + 1 < len(wrappers) else struct_type)
            if kind == "optional":
                while target_ptr.type.pointee != inner_type:
                    optional_type = target_ptr.type.pointee
                    if (not isinstance(optional_type, ir.LiteralStructType)
                            or len(optional_type.elements) != 2
                            or optional_type.elements[0] != ir.IntType(1)):
                        return False
                    tag_ptr = self.builder.gep(
                        target_ptr, [zero, zero], inbounds=True,
                        name="wrapped.optional.tag")
                    tag_commits.append((
                        tag_ptr, ir.Constant(ir.IntType(1), 1)))
                    target_ptr = self.builder.gep(
                        target_ptr,
                        [zero, ir.Constant(ir.IntType(32), 1)],
                        inbounds=True, name="wrapped.optional.value")
                continue

            enum_name = self._get_result_enum_name(saw_type)
            enum_type, variant_tags, variant_info = self.enum_types[enum_name]
            variant = "Err" if is_err else "Ok"
            params = variant_info[variant]
            if (len(params) != 1
                    or target_ptr.type.pointee != enum_type):
                return False
            tag_ptr = self.builder.gep(
                target_ptr, [zero, zero], inbounds=True,
                name="wrapped.result.tag")
            tag_commits.append((
                tag_ptr,
                ir.Constant(ir.IntType(32), variant_tags[variant])))
            payload_ptr = self.builder.gep(
                target_ptr, [zero, ir.Constant(ir.IntType(32), 1)],
                inbounds=True, name="wrapped.result.payload")
            param_type = ir.LiteralStructType([
                self._get_llvm_type(param_saw) for _, param_saw in params
            ])
            param_ptr = self.builder.bitcast(
                payload_ptr, param_type.as_pointer(),
                name="wrapped.result.variant")
            target_ptr = self.builder.gep(
                param_ptr, [zero, zero], inbounds=True,
                name="wrapped.result.value")
            if target_ptr.type.pointee != inner_type:
                return False

        if destination_optional:
            while target_ptr.type.pointee != struct_type:
                optional_type = target_ptr.type.pointee
                if (not isinstance(optional_type, ir.LiteralStructType)
                        or len(optional_type.elements) != 2
                        or optional_type.elements[0] != ir.IntType(1)):
                    return False
                tag_ptr = self.builder.gep(
                    target_ptr, [zero, zero], inbounds=True,
                    name="wrapped.optional.tag")
                tag_commits.append((
                    tag_ptr, ir.Constant(ir.IntType(1), 1)))
                target_ptr = self.builder.gep(
                    target_ptr,
                    [zero, ir.Constant(ir.IntType(32), 1)],
                    inbounds=True, name="wrapped.optional.value")

        if target_ptr.type.pointee != struct_type:
            return False
        self._materialize_struct_init(
            literal, target_ptr, _already_zeroed=already_zeroed)
        if not self.builder.block.is_terminated:
            for tag_ptr, tag_value in reversed(tag_commits):
                self.builder.store(tag_value, tag_ptr)
        return True

    def _materialize_struct_init(self, expr, dest_ptr,
                                 _already_zeroed=False):
        """Materialize one struct literal, optionally into caller-owned memory.

        `dest_ptr=None` is the SSA-only path used by returns, ordinary by-value
        call arguments and operands.  Every known-memory entry routes here:
        let/var initializers and every assignment target in `statements.py`,
        nested memberwise fields below, fixed-array/tuple stored elements in
        `collections.py`, and compiler-marked collection or boxed-frame
        transfers through `_gen_transfer_value`.

        A parsed `name(label: value)` that the typechecker reinterpreted as a
        function call, and a real custom `init`, remain calls.  With a
        destination their returned value is stored; their bodies are never
        replaced by memberwise construction.
        """
        materialized = self._as_memberwise_struct_init(expr)
        if materialized is not None:
            expr = materialized
        if expr.as_function_call is not None:
            value = self._generate_function_call(expr.as_function_call)
            if dest_ptr is None:
                return value
            if value is not None:
                self._store_transfer(value, dest_ptr)
            return None

        struct_name, llvm_struct_type, field_order, field_types = \
            self._struct_init_info(expr)

        if expr.resolved_init_params is not None:
            value = self._generate_custom_struct_init(expr, struct_name)
            if dest_ptr is None:
                return value
            self._store_transfer(value, dest_ptr)
            return None

        field_indices = {name: i for i, name in enumerate(field_order)}

        if dest_ptr is None:
            # Preserve the original SSA path exactly where no memory destination
            # exists.  Evaluation follows source order; insertion follows layout.
            field_values = {}
            for field_name, value_expr in expr.field_inits:
                i = field_indices[field_name]
                value = self._prepare_struct_field_value(
                    value_expr, field_types.get(field_name),
                    llvm_struct_type.elements[i])
                if value is None and self.builder.block.is_terminated:
                    return None
                field_values[field_name] = value
            result = ir.Constant(llvm_struct_type, ir.Undefined)
            for i, field_name in enumerate(field_order):
                result = self.builder.insert_value(
                    result, field_values[field_name], i)
            return result

        if dest_ptr.type.pointee != llvm_struct_type:
            raise ValueError(
                f"struct materialization destination has type "
                f"`{dest_ptr.type.pointee}`, expected `{llvm_struct_type}`")

        zeroed_fields = set(expr.zeroed_fields)
        zero_destination = bool(expr.zero_initialize)
        present_optional_fields = set(expr.present_optional_fields)
        if zero_destination and not _already_zeroed:
            self._emit_zero_fill(dest_ptr, llvm_struct_type)

        # A destination materialization owns each completed field immediately.
        # Keep those fields in a nested cleanup scope until the whole aggregate
        # is complete.  A propagating `try` sees this scope and drops the
        # initialized prefix in reverse order; success pops the bookkeeping
        # without dropping because ownership has transferred to the aggregate.
        partial_scope = []
        self.cleanup_stack.append(partial_scope)
        try:
            # Source order is semantic. Nested memberwise construction recurses
            # through direct, Optional, and Result destinations so only the
            # wrapper tags/union packing remain around in-place field stores.
            for field_name, value_expr in expr.field_inits:
                if zero_destination and field_name in zeroed_fields:
                    continue
                i = field_indices[field_name]
                field_ptr = self.builder.gep(
                    dest_ptr,
                    [ir.Constant(ir.IntType(32), 0),
                     ir.Constant(ir.IntType(32), i)],
                    inbounds=True, name=f"{field_name}.init")
                expected = llvm_struct_type.elements[i]
                if field_name in present_optional_fields:
                    self._materialize_present_optional_field(
                        value_expr, field_ptr, expected)
                    if self.builder.block.is_terminated:
                        return None
                    field_type = field_types.get(field_name)
                    if (field_type is not None
                            and self._needs_cleanup(field_type)):
                        partial_scope.append((
                            f"partial.{field_name}", field_type,
                            field_ptr, None))
                    continue
                if self._store_none_optional_tag(value_expr, field_ptr):
                    continue
                if self._materialize_wrapped_struct_init(
                        value_expr, field_ptr,
                        already_zeroed=(
                            zero_destination or _already_zeroed)):
                    if self.builder.block.is_terminated:
                        return None
                    field_type = field_types.get(field_name)
                    if (field_type is not None
                            and self._needs_cleanup(field_type)):
                        partial_scope.append((
                            f"partial.{field_name}", field_type,
                            field_ptr, None))
                    continue
                if (isinstance(value_expr, ArrayLiteral)
                        and hasattr(self, "_materialize_array_literal_into")
                        and self._materialize_array_literal_into(
                            value_expr, field_ptr,
                            already_zeroed=(
                                zero_destination or _already_zeroed))):
                    if self.builder.block.is_terminated:
                        return None
                    field_type = field_types.get(field_name)
                    if (field_type is not None
                            and self._needs_cleanup(field_type)):
                        partial_scope.append((
                            f"partial.{field_name}", field_type,
                            field_ptr, None))
                    continue
                value = self._prepare_struct_field_value(
                    value_expr, field_types.get(field_name), expected)
                if value is None and self.builder.block.is_terminated:
                    return None
                self._store_materialized_or_transfer(
                    value, field_ptr, final_use=True)
                field_type = field_types.get(field_name)
                if (field_type is not None
                        and self._needs_cleanup(field_type)):
                    partial_scope.append((
                        f"partial.{field_name}", field_type, field_ptr, None))
        finally:
            popped = self.cleanup_stack.pop()
            if popped is not partial_scope:
                raise ValueError(
                    "struct materialization cleanup scope was not innermost")
        return None

    _UNSIGNED_INT_KINDS = {
        TypeKind.UINT, TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64,
    }
    _INT_KINDS = _UNSIGNED_INT_KINDS | {
        TypeKind.INT, TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
    }

    def _coerce_int_to_field(self, value, field_type, value_expr):
        """Coerce an integer `value` to a fixed-width field's exact LLVM type.

        A bare integer literal (an i64 platform word on a hosted build) assigned
        to a narrower/wider fixed-width field is retyped to the field's width. A
        constant that does not fit the field is rejected with the standard range
        error (never an ICE); a runtime integer is truncated, or WIDENED through
        the design-195 funnel — by the SOURCE's signedness, which is what
        preserves the value. This arm read the FIELD's signedness until then, so
        an unsigned value flowing into a wider signed field sign-extended
        (DF-195a's field position).
        """
        resolved = self._resolve_type_alias(field_type) if field_type is not None else field_type
        if resolved is None or resolved.kind not in self._INT_KINDS:
            return value
        field_llvm = self._get_llvm_type(field_type)
        if not (isinstance(value.type, ir.IntType) and isinstance(field_llvm, ir.IntType)):
            return value
        if value.type.width == field_llvm.width:
            return value
        signed = self._int_type_is_signed(resolved)   # design 252's authority
        width = field_llvm.width
        if isinstance(value, ir.Constant):
            v = value.constant
            lo = -(1 << (width - 1)) if signed else 0
            hi = (1 << (width - 1)) - 1 if signed else (1 << width) - 1
            if not (lo <= v <= hi):
                line = getattr(value_expr, 'line', '?')
                raise ValueError(
                    f"integer literal {v} does not fit in `{field_type}` "
                    f"(range {lo}..={hi}) (line {line})")
            return ir.Constant(field_llvm, v)
        if value.type.width > width:
            return self.builder.trunc(value, field_llvm, name="field_trunc")
        return self._widen_int_value(
            value, field_llvm, getattr(value_expr, 'resolved_type', None))

    # Design 53 integer limits: (type name) -> (bit width or None for platform,
    # is_signed). Shared with the constant evaluator (design 148), so the value
    # a `static_assert` folds and the value this emits can never disagree.
    _INT_LIMIT_SPECS = INT_LIMIT_SPECS

    # ------------------------------------------------------------------
    # design 263 L2 — a field read is a GEP and one scalar load
    # ------------------------------------------------------------------

    def _struct_field_index(self, obj_type, member):
        """Position of `member` in the struct LLVM type `obj_type`, or None.

        THE struct-field resolution both member-access paths share: identified
        types answer by name, literal ones by layout string. Split out of
        `_generate_member_access` so the narrow read and the value projection
        cannot disagree about which field a name denotes.
        """
        struct_name = None
        if getattr(obj_type, 'name', None) in self.struct_types:
            struct_name = obj_type.name
        else:
            for name, (llvm_type, _) in self.struct_types.items():
                if str(obj_type) == str(llvm_type):
                    struct_name = name
                    break
        if struct_name is None:
            return None
        _, field_order = self.struct_types[struct_name]
        if member not in field_order:
            return None
        return field_order.index(member)

    def _addressable_place(self, expr) -> bool:
        """Whether `_get_lvalue_pointer` reaches `expr`'s real storage.

        The narrow read may only run over shapes that address storage the
        program already has. `_get_lvalue_pointer`'s last resort MATERIALIZES a
        temporary and stores the whole value into it — for a read that would be
        strictly worse than the aggregate load it replaces, so every shape that
        would land there is refused here instead.

        The list is `_is_owned_temporary`'s borrows: an identifier, `self`, a
        field of one of those, and — since design 263 U3b — a FIXED-ARRAY
        element of one of those. `_get_element_pointer` emits the very same
        `_emit_array_bounds_check` the value read emits, over the same count, so
        addressing the element changes nothing a program can observe.

        A `TupleIndex` base is deliberately absent: the evidence that drove U3b
        is fixed arrays, and a tuple slot has no measured case behind it.
        """
        if isinstance(expr, SelfExpr):
            return "self" in self.variables
        if isinstance(expr, Identifier):
            return (expr.name in self.variables
                    or self._static_global(expr) is not None)
        if isinstance(expr, ArrayIndex):
            # Only a FIXED array: that is the one container whose element
            # `_get_element_pointer` reaches with a two-index GEP and the
            # ordinary bounds check. A `Vector`/`Map` subscript is a design-146
            # place with its own lowering, and an `UnsafePointer` buffer is
            # unchecked by construction — neither belongs on this path.
            if expr.um_projection:
                return False
            if not self._addressable_place(expr.array_expr):
                return False
            container_type = self._expr_type(expr.array_expr)
            return (container_type is not None
                    and getattr(container_type, 'array_size', None) is not None)
        if isinstance(expr, ForceUnwrap):
            return (bool(getattr(expr, "frame_place_read", False))
                    and self._addressable_place(expr.expr))
        if isinstance(expr, MemberAccess):
            # Only a plain struct field nests. Every other MemberAccess meaning
            # — a folded constant, an integer limit, a named-tuple slot, an
            # UnsafeMemory projection, a module static, an enum variant — is
            # resolved its own way by the main walk, and re-deriving those here
            # would be the second copy of a rule that has one place.
            if (expr.const_folded_value is not None
                    or expr.int_limit is not None
                    or expr.tuple_field_index is not None
                    or expr.um_projection
                    or expr.resolved_static_name is not None
                    or expr.resolved_type_identity is not None
                    or self._static_global(expr) is not None):
                return False
            return self._addressable_place(expr.object)
        return False

    def _narrow_field_read(self, expr: MemberAccess):
        """`place.field` as a GEP and one scalar load, or None when it does not apply.

        Design 263 L2. sawc read a field by loading the WHOLE aggregate and
        `extractvalue`-ing one member out of the SSA value — 825 aggregate loads
        in the sos kernel IR, 58 of them 64 bytes or more, to read one word.
        InstCombine unpacks such a load into a scalar load per field, so the
        cost is not just the bytes moved: it is a load for every field the
        reader did not ask for, plus a `Bool` renormalization on each flag.

        Two ways the storage is in hand. The object expression may itself
        EVALUATE to a pointer — design 261 made every aggregate `&self` arrive
        that way, which is the kernel's dominant shape — or it may be an
        `_addressable_place` whose storage `_get_lvalue_pointer` names. Both end
        at the same GEP.

        Returns None whenever the field cannot be named from the pointee type,
        which leaves the value projection below to answer exactly as it did.
        """
        obj = expr.object
        if isinstance(obj, (Identifier, SelfExpr, MemberAccess, ArrayIndex)):
            if not self._addressable_place(obj):
                return None
            base_ptr = self._get_lvalue_pointer(obj)
            # An identifier bound to a POINTER (a by-pointer receiver forwarded
            # onward, a `Box`) is storage holding storage: step through once, so
            # the GEP lands on the struct rather than on the slot holding it.
            pointee = base_ptr.type.pointee
            if isinstance(pointee, ir.PointerType):
                base_ptr = self.builder.load(base_ptr, name="deref_ptr")
        else:
            # Anything else takes the VALUE path below, which is where the
            # ownership machinery lives: an owned temporary owes
            # `_register_stmt_temp` the whole value, and `_is_owned_temporary`
            # is what decides whether it is one.
            #
            # SL-213: this arm used to restate that predicate's node list
            # VERBATIM — a second copy of a list that had already gone stale
            # once. Both spellings answered `None` identically, so the
            # duplicate bought nothing and could only drift; the one question
            # is now asked in the one place that owns it.
            return None

        if not isinstance(base_ptr.type, ir.PointerType):
            return None
        field_index = self._struct_field_index(base_ptr.type.pointee,
                                               expr.member)
        if field_index is None:
            return None

        i32 = ir.IntType(32)
        field_ptr = self.builder.gep(
            base_ptr, [ir.Constant(i32, 0), ir.Constant(i32, field_index)],
            inbounds=True, name=f"{expr.member}_addr")
        return self._load_field(field_ptr, name=expr.member)

    def _generate_member_access(self, expr: MemberAccess):
        """Generate code for member access on structs or enum variant access."""
        # design 257 §2: a LONE raw-backed enum case the adoption funnel folded
        # into an integer slot. The same opening `_generate_binary_op` and
        # `_generate_unary_op` have (DF-235a/b), and for the same reason: the
        # typechecker range-checked the value AT the slot's type, so emit the
        # constant there rather than building an enum value at the backing
        # width for the store to reconcile.
        folded_type = expr.resolved_type or expr.expected_type
        if expr.const_folded_value is not None and folded_type is not None:
            return ir.Constant(self._get_llvm_type(folded_type),
                               expr.const_folded_value)

        # Design 53: integer limits `Int.max`/`Int.min` (and every fixed-width
        # type). Platform `Int`/`UInt` use the target word width so a riscv32
        # build gets 32-bit bounds; fixed-width types use their own width.
        limit = expr.int_limit
        if limit is not None:
            type_name, which = limit
            width, signed = self._INT_LIMIT_SPECS[type_name]
            if width is None:
                width = self.int_width
                llvm_ty = self.int_type
            else:
                llvm_ty = ir.IntType(width)
            if which == "max":
                value = (1 << (width - 1)) - 1 if signed else (1 << width) - 1
            else:  # min
                value = -(1 << (width - 1)) if signed else 0
            return ir.Constant(llvm_ty, value)

        # Named-tuple field access (design 63): the typechecker stamped the
        # resolved position; extract that element from the tuple value.
        tfi = expr.tuple_field_index
        if tfi is not None:
            obj_val = self._generate_expression(expr.object)
            return self.builder.extract_value(obj_val, tfi, name=f"tup_{expr.member}")

        # design 46: UnsafeMemory projection — `UM<Struct, Use>.field` computes
        # base + compile-time field offset WITHOUT loading the aggregate.
        if expr.um_projection:
            return self._generate_um_member_projection(expr)

        # Module-qualified static read (design 41): `mod.NAME`. The typechecker
        # tagged the member; codegen resolves the static by simple name in the
        # merged module and loads through its global.
        static_name = expr.resolved_static_name
        if static_name is not None and static_name in self.static_globals:
            gv = self.static_globals[static_name]
            return self.builder.load(gv, name=static_name)

        # Design 144: the typechecker resolved this variant literal's enum and
        # stamped its identity. Take that over any name matching below — the
        # written `Color` may denote a different enum in a different module.
        _eid = expr.resolved_type_identity
        if _eid is not None and (_eid in self.enum_types
                                 or _eid in self.generic_enums):
            return self._generate_enum_init(EnumInit(
                enum_name=_eid,
                variant_name=expr.member,
                arguments=[],
                type_args=getattr(expr.object, 'type_args', None),
                line=expr.line,
                column=expr.column,
            ))

        # Special case: EnumName.VariantName (simple variant with no associated values)
        # Check both concrete enums and generic enums
        if isinstance(expr.object, Identifier):
            is_enum = expr.object.name in self.enum_types
            is_generic_enum = expr.object.name in self.generic_enums
            if is_enum or is_generic_enum:
                # This is an enum variant access - convert to EnumInit
                enum_init = EnumInit(
                    enum_name=expr.object.name,
                    variant_name=expr.member,
                    arguments=[],
                    type_args=expr.object.type_args,  # Pass type_args for generic enums
                    line=expr.line,
                    column=expr.column
                )
                return self._generate_enum_init(enum_init)

        # Handle module-qualified enum variant access: lib.Color.Red
        if isinstance(expr.object, MemberAccess) and expr.resolved_module is not None:
            # The typechecker resolved this as a module-qualified enum variant
            # expr.object is something like lib.Color (a MemberAccess to an enum type)
            enum_name = expr.object.member  # The enum name (e.g., "Color")
            if enum_name in self.enum_types or enum_name in self.generic_enums:
                enum_init = EnumInit(
                    enum_name=enum_name,
                    variant_name=expr.member,
                    arguments=[],
                    type_args=getattr(expr.object, 'type_args', None),
                    line=expr.line,
                    column=expr.column
                )
                return self._generate_enum_init(enum_init)

        # design 263 L2: the field lives in memory, so read THAT field — a GEP
        # and one scalar load — instead of loading the whole aggregate into an
        # SSA value and projecting one member out of it.
        narrow = self._narrow_field_read(expr)
        if narrow is not None:
            return narrow

        obj_val = self._generate_expression(expr.object)

        # DF-217m: a statement-scoped temporary RECEIVER, exactly as a method
        # call registers one (`makeResource().use()`). `mk(3).n` builds a value
        # nobody else owns — it is not bound, returned or transferred onward —
        # and reading a field out of it left the value itself unreleased. An
        # lvalue object (an identifier, `self`, a field, an element) is owned by
        # its binding and is NOT registered here, which would double-free it.
        if self._is_owned_temporary(expr.object):
            self._register_stmt_temp(obj_val, self._expr_type(expr.object))

        # Determine the struct type
        # For now, we need to infer the struct type from the object expression
        # This is a bit hacky, but works for simple cases
        # In a more sophisticated system, we'd track type info through the codegen

        # For now, assume the object is a struct and find which one based on its LLVM type
        obj_type = obj_val.type

        # Handle pointer to struct (e.g., var self methods). The narrow read
        # above already took this shape whenever it could name the field; what
        # is left here is a pointee `_struct_field_index` could not resolve.
        is_pointer = isinstance(obj_type, ir.PointerType)
        if is_pointer:
            # Load the struct value from the pointer
            obj_val = self.builder.load(obj_val, name="deref")
            obj_type = obj_val.type

        field_index = self._struct_field_index(obj_type, expr.member)
        if field_index is not None:
            return self.builder.extract_value(obj_val, field_index)

        # Debug: print available struct types
        for name, (llvm_type, fields) in self.struct_types.items():
            print(f"  {name}: {llvm_type} -> {fields}")
        raise ValueError(f"Cannot find field {expr.member} in struct with type {obj_type}")

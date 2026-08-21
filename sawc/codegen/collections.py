"""
Collection expression generation for the Saw code generator.

This module provides mixin methods for generating LLVM IR code for tuple
and array expressions including literals and indexing.

Usage:
    class CodeGenerator(CollectionsMixin, ...):
        pass
"""

from llvmlite import ir
from ast_nodes import (TupleLiteral, TupleIndex, ArrayLiteral, ArrayIndex, IntLiteral,
                       MapLiteral, SetLiteral, FunctionCall, MethodCall, Identifier,
                       Argument, SawType, TypeKind)
from const_eval import const_eval


class CollectionsMixin:
    """Mixin providing collection generation methods for CodeGenerator.

    Methods:
        _generate_tuple_literal: Generate code for tuple literals
        _generate_tuple_index: Generate code for tuple indexing
        _generate_array_literal: Generate code for array literals
        _generate_array_index: Generate code for array/tuple/pointer indexing
    """

    def _generate_tuple_literal(self, expr: TupleLiteral):
        """Generate code for a tuple literal."""
        # Generate each element (honoring Copy needs_copy annotations), each
        # coerced to the DECLARED element type — an annotated tuple's element
        # widths are the annotation's, not the written elements' (DF-205a).
        declared = getattr(expr, 'resolved_type', None)
        elem_saws = (declared.element_types
                     if declared is not None and declared.element_types else None)
        element_values = [self._gen_transfer_value(elem) for elem in expr.elements]
        if elem_saws is not None and len(elem_saws) == len(element_values):
            element_values = [
                self._coerce_element_int(v, e, t)
                for v, e, t in zip(element_values, expr.elements, elem_saws)]

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

    def _build_collection_literal(self, container_type, expr, method_name,
                                  insert_arg_lists, discard_saw_type=None):
        """Shared lowering for map / set / vector literals (design 54): construct
        the container, then call `method_name` (insert/push) once per element in
        source order, and yield the finished value.

        The container is built through the SAME code paths as a hand-written
        `Container<..>()` + `.insert(...)`/`.push(...)`, so monomorphization,
        value-transfer (moves/copies of owning elements), and Deinit all behave
        identically. A synthetic local binds the temp so the synthesized
        `insert`/`push` method calls resolve their `&var self` receiver.

        `discard_saw_type` is the type of each call's discarded return value
        (Map.insert returns the shadowed old value `V?`); when it needs cleanup,
        the return is dropped like a discarded call result so a duplicate-key map
        literal with owning values does not leak the shadowed value."""
        ct = container_type
        if ct is not None and self.type_param_context:
            ct = ct.substitute(self.type_param_context)
        type_name = ct.struct_name

        # Construct: `Container<..>()` via the init(): route through the normal
        # struct-init path (custom no-arg init) so the type + all its methods
        # monomorphize.
        init_call = FunctionCall(name=type_name, arguments=[],
                                 type_args=list(ct.type_args),
                                 line=expr.line, column=expr.column)
        init_call.resolved_type = ct
        init_call.resolved_init_params = []
        cont_val = self._generate_expression(init_call)

        tmp_ptr = self._entry_alloca(cont_val.type, name=type_name.lower() + "lit")
        self.builder.store(cont_val, tmp_ptr)

        # design 168 unit 3 (DF-164a): named from the literal's own SOURCE
        # POSITION, not its `node_id`. A node id is a process-global counter, so
        # this name shifted with how much had been parsed before the literal —
        # two compiles of one file in one process emitted `%"__collit_14189"` and
        # `%"__collit_29638"`, and any std cache (which changes the order ids are
        # allocated in) moved every one of them. A position is a property of the
        # source and nothing else.
        tmpname = self._positional_local(expr, "__collit")
        self.variables[tmpname] = tmp_ptr
        self.variable_types[tmpname] = ct
        try:
            for arg_list in insert_arg_lists:
                obj = Identifier(name=tmpname, line=expr.line, column=expr.column)
                obj.resolved_type = ct
                mc = MethodCall(
                    object=obj, method_name=method_name,
                    arguments=[Argument(value=a, name=None) for a in arg_list],
                    line=expr.line, column=expr.column)
                res = self._generate_expression(mc)
                # Drop an owning discarded return (Map.insert's shadowed `V?` on a
                # duplicate key) so it is not leaked — same as a discarded call
                # result at statement end.
                if (discard_saw_type is not None and res is not None
                        and not isinstance(res.type, ir.VoidType)
                        and self._needs_cleanup(discard_saw_type)):
                    ret_slot = self._entry_alloca(res.type, name="collit_discard")
                    self.builder.store(res, ret_slot)
                    self._emit_drop_at(ret_slot, discard_saw_type)
        finally:
            self.variables.pop(tmpname, None)
            self.variable_types.pop(tmpname, None)

        return self.builder.load(tmp_ptr, name=type_name.lower() + "lit_val")

    def _generate_map_literal(self, expr: MapLiteral):
        """Lower a map literal `{k: v, ...}` / `{:}` (design 54)."""
        ct = expr.resolved_type
        # Map.insert returns the shadowed old value `V?`; a duplicate key inside
        # the literal discards it, so pass its type to be dropped (only owning V
        # actually needs it). V is the map's second type arg.
        discard = None
        sub = ct.substitute(self.type_param_context) if (ct is not None and self.type_param_context) else ct
        if sub is not None and sub.type_args and len(sub.type_args) >= 2:
            discard = SawType(TypeKind.OPTIONAL, inner_type=sub.type_args[1])
        return self._build_collection_literal(
            ct, expr, "insert", [[k, v] for (k, v) in expr.entries],
            discard_saw_type=discard)

    def _generate_set_literal(self, expr: SetLiteral):
        """Lower a set literal `{a, b, ...}` (design 54)."""
        ct = expr.resolved_type
        return self._build_collection_literal(
            ct, expr, "insert", [[e] for e in expr.elements])

    def _generate_array_literal(self, expr: ArrayLiteral):
        """Generate code for array literal.

        Design 54 Part 4: when the typechecker stamped a `Vector<T, A>` expected
        type, build a Vector (per-element push) instead of a fixed-size array."""
        vec_ct = expr.vector_container_type
        if vec_ct is not None:
            return self._build_collection_literal(
                vec_ct, expr, "push", [[e] for e in expr.elements])

        if expr.repeat_count is not None:
            return self._generate_repeat_literal(expr)

        if len(expr.elements) == 0:
            raise ValueError("Empty array literals not supported")

        # Generate all element values (honoring Copy needs_copy annotations),
        # each coerced to the DECLARED element type (DF-205a): the array's
        # element type is the ANNOTATION's, not element 0's, so a literal whose
        # first element is narrower than the annotation no longer builds a
        # too-narrow array that the second element cannot be inserted into.
        arr_saw = getattr(expr, 'resolved_type', None)
        elem_saw = arr_saw.array_element_type if arr_saw is not None else None
        element_values = [self._gen_transfer_value(elem) for elem in expr.elements]
        element_values = [self._coerce_element_int(v, e, elem_saw)
                          for v, e in zip(element_values, expr.elements)]

        # Get the element type from the first element
        elem_type = element_values[0].type
        array_type = ir.ArrayType(elem_type, len(element_values))

        # Build the array value by inserting elements
        array_val = ir.Constant(array_type, ir.Undefined)
        for i, val in enumerate(element_values):
            array_val = self.builder.insert_value(array_val, val, i, name=f"arr_{i}")

        return array_val

    # A constant repeat wider than this emits a splat loop rather than an
    # N-entry constant array: the constant is correct at any width, but it is
    # spelled out element by element in the IR, and `[4096 x i8]` written long
    # hand is worse for compile time than a four-instruction loop. An all-zero
    # constant is exempt — it spells `zeroinitializer` at any width, which is
    # the memset the repeat literal exists to give you.
    _REPEAT_CONST_LIMIT = 32

    def _generate_repeat_literal(self, expr: ArrayLiteral):
        """Lower `[v; N]` — N copies of one value (design 148).

        Three shapes, cheapest first: an all-zero constant becomes
        `zeroinitializer` (which is the memset — `[0; 4096]` is one store); a
        small non-zero constant becomes a constant array; anything else stores
        the value into an alloca through a counted loop. The value expression is
        evaluated EXACTLY ONCE either way, which is what makes the element's
        copy policy the typechecker's business rather than a surprise here.
        """
        arr_saw = expr.resolved_type
        count = arr_saw.array_size if arr_saw is not None else None
        if count is None:
            # An abstract generic body stamped a length it could not evaluate;
            # this instantiation can (design 148 unit C).
            count = const_eval(expr.repeat_count, env=self._const_param_env(),
                               metric=self._const_type_metric,
                               width=self.int_width)
        elem_saw = arr_saw.array_element_type if arr_saw is not None else None
        needs_cleanup = elem_saw is not None and self._needs_cleanup(elem_saw)

        value = self._gen_transfer_value(expr.elements[0])
        array_type = ir.ArrayType(value.type, count)

        if count == 0:
            # No slot takes the value, so the one reference it owns has to go
            # somewhere — dropping it on the floor would leak.
            if needs_cleanup:
                tmp = self._entry_alloca(value.type, name="repeat_unused")
                self.builder.store(value, tmp)
                self._emit_release_at(tmp, elem_saw)
            return ir.Constant(array_type, None)

        if isinstance(value, ir.Constant) and not needs_cleanup:
            if self._is_zero_constant(value):
                return ir.Constant(array_type, None)      # zeroinitializer
            if count <= self._REPEAT_CONST_LIMIT:
                return ir.Constant(array_type, [value] * count)

        # Splat loop. Slot 0 takes the value's own reference; every later slot
        # takes a fresh one, which is why the retain is inside the loop and the
        # loop starts at 1.
        i32 = ir.IntType(32)
        zero32 = ir.Constant(i32, 0)
        arr_ptr = self._entry_alloca(array_type, name="repeat")
        first = self.builder.gep(arr_ptr, [zero32, zero32], name="repeat_0")
        self.builder.store(value, first)

        if count > 1:
            idx_ptr = self._entry_alloca(self.int_type, name="repeat_i")
            self.builder.store(ir.Constant(self.int_type, 1), idx_ptr)
            cond_bb = self.builder.append_basic_block("repeat_cond")
            body_bb = self.builder.append_basic_block("repeat_body")
            done_bb = self.builder.append_basic_block("repeat_done")

            self.builder.branch(cond_bb)
            self.builder.position_at_end(cond_bb)
            i = self.builder.load(idx_ptr, name="repeat_idx")
            self.builder.cbranch(
                self.builder.icmp_signed(
                    '<', i, ir.Constant(self.int_type, count), name="repeat_more"),
                body_bb, done_bb)

            self.builder.position_at_end(body_bb)
            elem_ptr = self.builder.gep(arr_ptr, [zero32, i], name="repeat_slot")
            self.builder.store(value, elem_ptr)
            if needs_cleanup:
                self._emit_retain_at(elem_ptr, elem_saw)
            self.builder.store(
                self.builder.add(i, ir.Constant(self.int_type, 1), name="repeat_next"),
                idx_ptr)
            self.builder.branch(cond_bb)

            self.builder.position_at_end(done_bb)

        return self.builder.load(arr_ptr, name="repeat_val")

    @classmethod
    def _is_zero_constant(cls, value) -> bool:
        """Whether an LLVM constant is the all-zero bit pattern.

        Aggregates count (design 149 unit b): a static's initializer decides
        whether the global can be zerofill, and the zero cases that matter there
        are `zeroinitializer` — which llvmlite spells as a Constant carrying no
        payload — and an element list that is zeros all the way down, which is
        what a spelled-out struct or array of zeros arrives as.
        """
        if not isinstance(value, ir.Constant):
            return False
        c = value.constant
        if c is None:
            return True                      # zeroinitializer
        if isinstance(c, bool):
            return c is False
        if isinstance(c, (int, float)):
            return c == 0
        if isinstance(c, (list, tuple)):
            return all(cls._is_zero_constant(e) for e in c)
        return False

    def _generate_array_index(self, expr: ArrayIndex):
        """Generate code for array or tuple indexing with [index] syntax."""
        # design 46: UnsafeMemory region indexing projects to an element address.
        if expr.um_projection:
            return self._generate_um_index_projection(expr)

        container_val = self._generate_expression(expr.array_expr)

        # Check if it's a tuple (struct type in LLVM) or array
        if isinstance(container_val.type, ir.ArrayType):
            # Array indexing - need to allocate, store, and use GEP
            index_val = self._generate_expression(expr.index)

            # Dynamic bounds check (design 63 T1b): panic on an out-of-range
            # index into a fixed array before the GEP/load.
            self._emit_array_bounds_check(index_val, container_val.type.count, expr.index)

            # Allocate space for the array on stack
            array_ptr = self._entry_alloca(container_val.type, name="arr_tmp")
            self.builder.store(container_val, array_ptr)

            # Use GEP to get pointer to element
            zero = ir.Constant(ir.IntType(64), 0)
            elem_ptr = self.builder.gep(array_ptr, [zero, index_val], name="elem_ptr")

            # Load the element
            return self.builder.load(elem_ptr, name="elem")

        elif isinstance(container_val.type, ir.LiteralStructType):
            # Tuple indexing - index must be a constant (checked by typechecker)
            if isinstance(expr.index, IntLiteral):
                index = expr.index.value
                return self.builder.extract_value(container_val, index, name="tuple_elem")
            else:
                raise ValueError("Tuple index must be a compile-time constant")

        elif isinstance(container_val.type, ir.PointerType):
            # Pointer indexing: ptr[i] - use GEP to offset and load
            index_val = self._generate_expression(expr.index)
            elem_ptr = self.builder.gep(container_val, [index_val], name="ptr_idx")
            return self.builder.load(elem_ptr, name="ptr_elem")

        else:
            raise ValueError(f"Cannot index into type: {container_val.type}")

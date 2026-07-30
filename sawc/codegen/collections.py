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
        # Generate each element (honoring ImplicitCopy needs_copy annotations)
        element_values = [self._gen_transfer_value(elem) for elem in expr.elements]

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

        tmpname = f"__collit_{id(expr)}"
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
        ct = getattr(expr, 'resolved_type', None)
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
        ct = getattr(expr, 'resolved_type', None)
        return self._build_collection_literal(
            ct, expr, "insert", [[e] for e in expr.elements])

    def _generate_array_literal(self, expr: ArrayLiteral):
        """Generate code for array literal.

        Design 54 Part 4: when the typechecker stamped a `Vector<T, A>` expected
        type, build a Vector (per-element push) instead of a fixed-size array."""
        vec_ct = getattr(expr, 'vector_container_type', None)
        if vec_ct is not None:
            return self._build_collection_literal(
                vec_ct, expr, "push", [[e] for e in expr.elements])

        if len(expr.elements) == 0:
            raise ValueError("Empty array literals not supported")

        # Generate all element values (honoring ImplicitCopy needs_copy annotations)
        element_values = [self._gen_transfer_value(elem) for elem in expr.elements]

        # Get the element type from the first element
        elem_type = element_values[0].type
        array_type = ir.ArrayType(elem_type, len(element_values))

        # Build the array value by inserting elements
        array_val = ir.Constant(array_type, ir.Undefined)
        for i, val in enumerate(element_values):
            array_val = self.builder.insert_value(array_val, val, i, name=f"arr_{i}")

        return array_val

    def _generate_array_index(self, expr: ArrayIndex):
        """Generate code for array or tuple indexing with [index] syntax."""
        # design 46: UnsafeMemory region indexing projects to an element address.
        if getattr(expr, 'um_projection', False):
            return self._generate_um_index_projection(expr)

        container_val = self._generate_expression(expr.array_expr)

        # Check if it's a tuple (struct type in LLVM) or array
        if isinstance(container_val.type, ir.ArrayType):
            # Array indexing - need to allocate, store, and use GEP
            index_val = self._generate_expression(expr.index)

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

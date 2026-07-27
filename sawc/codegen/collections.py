"""
Collection expression generation for the Saw code generator.

This module provides mixin methods for generating LLVM IR code for tuple
and array expressions including literals and indexing.

Usage:
    class CodeGenerator(CollectionsMixin, ...):
        pass
"""

from llvmlite import ir
from ast_nodes import TupleLiteral, TupleIndex, ArrayLiteral, ArrayIndex, IntLiteral


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

    def _generate_array_literal(self, expr: ArrayLiteral):
        """Generate code for array literal."""
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

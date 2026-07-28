"""
Optional type handling for the Saw code generator.

This module provides mixin methods for generating code that handles optional types,
including None literals, force unwrap (!), nil coalescing (??), and optional
chaining (?.).

Optional representation:
- Optionals are represented as { i1, T } where i1 indicates presence (is_some)
- None is { 0, undefined }
- Some(value) is { 1, value }

Usage:
    class CodeGenerator(OptionalsMixin, ...):
        pass
"""

from llvmlite import ir
from ast_nodes import NoneLiteral, ForceUnwrap, NilCoalesce, OptionalChain, OptionalWrap


class OptionalsMixin:
    """Mixin providing optional type handling methods for CodeGenerator.

    Methods:
        _wrap_in_optional: Wrap a value in an optional (Some)
        _is_optional_type: Check if an LLVM type is an optional
        _generate_none_literal: Generate code for None
        _generate_force_unwrap: Generate code for expr!
        _generate_nil_coalesce: Generate code for expr ?? default
        _generate_optional_chain: Generate code for expr?.member
    """

    def _wrap_in_optional(self, value):
        """Wrap a value in an optional type (for implicit wrapping)."""
        optional_type = ir.LiteralStructType([ir.IntType(1), value.type])
        optional_val = ir.Constant(optional_type, ir.Undefined)

        # Set is_some to true
        true_val = ir.Constant(ir.IntType(1), 1)
        optional_val = self.builder.insert_value(optional_val, true_val, 0)

        # Set the value
        optional_val = self.builder.insert_value(optional_val, value, 1)

        return optional_val

    def visit_OptionalWrap(self, expr: OptionalWrap):
        """Generate code for OptionalWrap (T -> T?).

        This is inserted by the typechecker when a value of type T
        is used where T? is expected.
        """
        value = self._generate_expression(expr.value)
        return self._wrap_in_optional(value)

    def _is_optional_type(self, llvm_type) -> bool:
        """Check if an LLVM type is an optional (struct with i1 flag and value)."""
        return (isinstance(llvm_type, ir.LiteralStructType) and
                len(llvm_type.elements) == 2 and
                llvm_type.elements[0] == ir.IntType(1))

    def _generate_none_literal(self, expr: NoneLiteral):
        """Generate code for None literal.

        Creates an optional with is_some = false. The inner type is determined
        from the typechecker's resolved_type annotation or the current function's
        return type.
        """
        # Create an optional with is_some = false. The inner type comes from the
        # typechecker annotation via the single accessor (which substitutes
        # generic bindings). A bare `None` whose optional inner type was never
        # pinned contextually falls back to the current function's return type.
        none_type = self._expr_type(expr)  # OPTIONAL, inner_type may be None
        inner_type = none_type.inner_type

        if inner_type is None and self.current_return_type and self.current_return_type.is_optional():
            inner_type = self.current_return_type.inner_type
            if inner_type and self.type_param_context:
                inner_type = inner_type.substitute(self.type_param_context)

        if inner_type is None:
            # No fallback - fail loudly so we can fix the root cause
            raise ValueError(
                f"None literal at line {expr.line} has no type information. "
                f"resolved_type={getattr(expr, 'resolved_type', None)}, "
                f"current_return_type={self.current_return_type}"
            )

        inner_llvm_type = self._get_llvm_type(inner_type)

        optional_type = ir.LiteralStructType([ir.IntType(1), inner_llvm_type])
        optional_val = ir.Constant(optional_type, ir.Undefined)

        # Set is_some to false
        false_val = ir.Constant(ir.IntType(1), 0)
        optional_val = self.builder.insert_value(optional_val, false_val, 0)

        return optional_val

    def _generate_force_unwrap(self, expr: ForceUnwrap):
        """Generate code for force unwrap (expr!).

        Extracts the value from an optional, panicking at runtime if the
        optional is None.
        """
        optional_val = self._generate_expression(expr.expr)

        # Extract the is_some flag
        is_some = self.builder.extract_value(optional_val, 0, name="is_some")

        # Runtime check: panic if None
        func = self.builder.function
        unwrap_ok_bb = func.append_basic_block(name="unwrap.ok")
        unwrap_panic_bb = func.append_basic_block(name="unwrap.panic")

        self.builder.cbranch(is_some, unwrap_ok_bb, unwrap_panic_bb)

        # Panic block: emit the panic via the saw_panic seam.
        self.builder.position_at_end(unwrap_panic_bb)
        self._emit_panic(f"panic: force unwrap of None at line {expr.line}")

        # OK block: extract and return the value
        self.builder.position_at_end(unwrap_ok_bb)
        return self.builder.extract_value(optional_val, 1, name="unwrapped")

    def _generate_nil_coalesce(self, expr: NilCoalesce):
        """Generate code for nil coalescing (expr ?? default).

        Returns the unwrapped value if present, otherwise evaluates and
        returns the default expression.
        """
        optional_val = self._generate_expression(expr.expr)

        # Extract the is_some flag
        is_some = self.builder.extract_value(optional_val, 0, name="is_some")

        # Create blocks for the conditional
        func = self.builder.function
        some_bb = func.append_basic_block(name="some")
        none_bb = func.append_basic_block(name="none")
        merge_bb = func.append_basic_block(name="coalesce_merge")

        self.builder.cbranch(is_some, some_bb, none_bb)

        # Some branch - extract the value
        self.builder.position_at_start(some_bb)
        some_val = self.builder.extract_value(optional_val, 1, name="some_value")
        self.builder.branch(merge_bb)
        some_bb = self.builder.block

        # None branch - evaluate default
        self.builder.position_at_start(none_bb)
        none_val = self._generate_expression(expr.default)
        self.builder.branch(merge_bb)
        none_bb = self.builder.block

        # Merge
        self.builder.position_at_start(merge_bb)
        phi = self.builder.phi(some_val.type, name="coalesced")
        phi.add_incoming(some_val, some_bb)
        phi.add_incoming(none_val, none_bb)

        return phi

    def _generate_optional_chain(self, expr: OptionalChain):
        """Generate code for optional chaining (expr?.member).

        If the optional contains a value, accesses the member and wraps the
        result in a new optional. If None, propagates None.
        """
        optional_val = self._generate_expression(expr.expr)

        # Extract the is_some flag
        is_some = self.builder.extract_value(optional_val, 0, name="is_some")

        # Create blocks
        func = self.builder.function
        some_bb = func.append_basic_block(name="chain_some")
        none_bb = func.append_basic_block(name="chain_none")
        merge_bb = func.append_basic_block(name="chain_merge")

        self.builder.cbranch(is_some, some_bb, none_bb)

        # Some branch - unwrap and access member
        self.builder.position_at_start(some_bb)
        unwrapped = self.builder.extract_value(optional_val, 1, name="unwrapped")

        # Access the member (assuming struct)
        # Find the struct type and field index
        unwrapped_type = unwrapped.type
        struct_name = None
        if hasattr(unwrapped_type, 'name') and unwrapped_type.name in self.struct_types:
            struct_name = unwrapped_type.name
        else:
            for name, (llvm_type, _) in self.struct_types.items():
                if str(unwrapped_type) == str(llvm_type):
                    struct_name = name
                    break

        member_val = None
        if struct_name:
            _, field_order = self.struct_types[struct_name]
            if expr.member in field_order:
                field_index = field_order.index(expr.member)
                member_val = self.builder.extract_value(unwrapped, field_index)

        if member_val is None:
            raise ValueError(f"Cannot find field {expr.member} for type {unwrapped_type}")

        # Wrap the result in an optional
        result_optional_type = ir.LiteralStructType([ir.IntType(1), member_val.type])
        some_result = ir.Constant(result_optional_type, ir.Undefined)
        some_result = self.builder.insert_value(some_result, ir.Constant(ir.IntType(1), 1), 0)
        some_result = self.builder.insert_value(some_result, member_val, 1)

        self.builder.branch(merge_bb)
        some_bb = self.builder.block

        # None branch - return None
        self.builder.position_at_start(none_bb)
        none_result = ir.Constant(result_optional_type, ir.Undefined)
        none_result = self.builder.insert_value(none_result, ir.Constant(ir.IntType(1), 0), 0)
        self.builder.branch(merge_bb)
        none_bb = self.builder.block

        # Merge
        self.builder.position_at_start(merge_bb)
        phi = self.builder.phi(result_optional_type, name="chained")
        phi.add_incoming(some_result, some_bb)
        phi.add_incoming(none_result, none_bb)

        return phi

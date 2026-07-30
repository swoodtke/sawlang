"""
Struct expression generation for the Saw code generator.

This module provides mixin methods for generating LLVM IR code for struct
initialization and member access expressions.

Usage:
    class CodeGenerator(StructsMixin, ...):
        pass
"""

from llvmlite import ir
from ast_nodes import StructInit, MemberAccess, Identifier, EnumInit


class StructsMixin:
    """Mixin providing struct generation methods for CodeGenerator.

    Methods:
        _generate_struct_init: Generate code for struct initialization
        _generate_member_access: Generate code for member access
    """

    def _generate_struct_init(self, expr: StructInit):
        """Generate code for struct initialization."""
        # Handle generic struct instantiation
        struct_name = expr.struct_name
        if expr.type_args:
            # Substitute type parameters in type args if we're in a generic context
            # e.g., Vector<T>(...) inside Vector<Int>.init() should become Vector<Int>(...)
            resolved_type_args = []
            for type_arg in expr.type_args:
                if self.type_param_context:
                    resolved = type_arg.substitute(self.type_param_context)
                    resolved_type_args.append(resolved)
                else:
                    resolved_type_args.append(type_arg)
            # This is a generic struct - ensure monomorphized version exists
            struct_name = self._ensure_monomorphized_struct(expr.struct_name, resolved_type_args)

        if struct_name not in self.struct_types:
            raise ValueError(f"Undefined struct: {struct_name}")

        # Check if this is a custom init method call
        if expr.resolved_init_params is not None:
            # Custom init - call the init method
            mangled_name = self._mangle_method_name(struct_name, "init", expr.resolved_init_params)
            init_func = self.functions[mangled_name]

            # Generate arguments in the order expected by the init method
            args = []
            param_to_value = {param_name: value for param_name, value in expr.field_inits}
            for param_name in expr.resolved_init_params:
                arg_value = self._gen_transfer_value(param_to_value[param_name])
                args.append(arg_value)

            # Call the init method
            return self.builder.call(init_func, args)

        # Field initialization (original behavior)
        llvm_struct_type, field_order = self.struct_types[struct_name]

        # Get field types for ImplicitCopy handling (use namespace)
        field_types = self.namespace.get_struct_fields(struct_name) or {}

        # Create a map from field name to value, handling ImplicitCopy
        field_values = {}
        for field_name, value_expr in expr.field_inits:
            value = self._generate_expression(value_expr)

            # Check if this field needs copy() called
            field_type = field_types.get(field_name)
            if field_type and self._needs_copy_for_struct_init(value_expr, field_type):
                value = self._generate_copy(value, field_type)

            field_values[field_name] = value

        # Build the struct value in the correct field order
        struct_val = ir.Constant(llvm_struct_type, ir.Undefined)
        for i, field_name in enumerate(field_order):
            if field_name in field_values:
                val = field_values[field_name]
                # Wrap a bare `T` into `T?` when the field is optional. An optional
                # is laid out `{ i1 is_some, T }`; wrap exactly when the field has
                # that shape AND the value is the inner `T` (not already an
                # optional). The old heuristic ("value is not a struct") misfired
                # for struct/enum payloads — an enum value is itself a
                # LiteralStructType, so it was wrongly treated as already-optional
                # and stored unwrapped (design 52: enum params of a coroutine
                # frame hit this).
                expected_field_type = llvm_struct_type.elements[i]
                if (isinstance(expected_field_type, ir.LiteralStructType)
                        and len(expected_field_type.elements) == 2
                        and expected_field_type.elements[0] == ir.IntType(1)
                        and val.type == expected_field_type.elements[1]):
                    val = self._wrap_in_optional(val)
                struct_val = self.builder.insert_value(struct_val, val, i)

        return struct_val

    # Design 53 integer limits: (type name) -> (bit width or None for platform, is_signed).
    _INT_LIMIT_SPECS = {
        'Int': (None, True), 'UInt': (None, False),
        'Int8': (8, True), 'Int16': (16, True), 'Int32': (32, True), 'Int64': (64, True),
        'UInt8': (8, False), 'UInt16': (16, False), 'UInt32': (32, False), 'UInt64': (64, False),
    }

    def _generate_member_access(self, expr: MemberAccess):
        """Generate code for member access on structs or enum variant access."""
        # Design 53: integer limits `Int.max`/`Int.min` (and every fixed-width
        # type). Platform `Int`/`UInt` use the target word width so a riscv32
        # build gets 32-bit bounds; fixed-width types use their own width.
        limit = getattr(expr, 'int_limit', None)
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

        # design 46: UnsafeMemory projection — `UM<Struct, Use>.field` computes
        # base + compile-time field offset WITHOUT loading the aggregate.
        if getattr(expr, 'um_projection', False):
            return self._generate_um_member_projection(expr)

        # Module-qualified static read (design 41): `mod.NAME`. The typechecker
        # tagged the member; codegen resolves the static by simple name in the
        # merged module and loads through its global.
        static_name = getattr(expr, 'resolved_static_name', None)
        if static_name is not None and static_name in self.static_globals:
            gv = self.static_globals[static_name]
            return self.builder.load(gv, name=static_name)

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
        if isinstance(expr.object, MemberAccess) and hasattr(expr, 'resolved_module'):
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

        obj_val = self._generate_expression(expr.object)

        # Determine the struct type
        # For now, we need to infer the struct type from the object expression
        # This is a bit hacky, but works for simple cases
        # In a more sophisticated system, we'd track type info through the codegen

        # For now, assume the object is a struct and find which one based on its LLVM type
        obj_type = obj_val.type

        # Handle pointer to struct (e.g., var self methods)
        is_pointer = isinstance(obj_type, ir.PointerType)
        if is_pointer:
            # Load the struct value from the pointer
            obj_val = self.builder.load(obj_val, name="deref")
            obj_type = obj_val.type

        # For identified types, get name directly
        struct_name = None
        if hasattr(obj_type, 'name') and obj_type.name in self.struct_types:
            struct_name = obj_type.name
        else:
            # Fallback to string comparison for literal types
            for name, (llvm_type, _) in self.struct_types.items():
                if str(obj_type) == str(llvm_type):
                    struct_name = name
                    break

        if struct_name and struct_name in self.struct_types:
            _, field_order = self.struct_types[struct_name]
            if expr.member in field_order:
                field_index = field_order.index(expr.member)
                result = self.builder.extract_value(obj_val, field_index)
                return result

        # Debug: print available struct types
        for name, (llvm_type, fields) in self.struct_types.items():
            print(f"  {name}: {llvm_type} -> {fields}")
        raise ValueError(f"Cannot find field {expr.member} in struct with type {obj_type}")

"""
Struct expression generation for the Saw code generator.

This module provides mixin methods for generating LLVM IR code for struct
initialization and member access expressions.

Usage:
    class CodeGenerator(StructsMixin, ...):
        pass
"""

from llvmlite import ir
from ast_nodes import (StructInit, MemberAccess, Identifier, EnumInit, TypeKind,
                       SelfExpr, FunctionCall, MethodCall, TupleLiteral,
                       ArrayLiteral, MapLiteral, SetLiteral)
from const_eval import INT_LIMIT_SPECS


class StructsMixin:
    """Mixin providing struct generation methods for CodeGenerator.

    Methods:
        _generate_struct_init: Generate code for struct initialization
        _generate_member_access: Generate code for member access
    """

    def _generate_struct_init(self, expr: StructInit):
        """Generate code for struct initialization."""
        # Design 66: the typechecker reinterpreted this `name(label: ...)` node
        # as a fully-labeled FUNCTION call (the parser could not tell struct init
        # from a labeled call). Emit the call instead of a struct build.
        as_call = expr.as_function_call
        if as_call is not None:
            return self._generate_function_call(as_call)
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
        elif struct_name in self.generic_structs:
            # A generic named with NO arguments: well-formed exactly when every
            # parameter is defaulted (design 37, and design 148 for a const
            # one). `Tag()` on a `struct Tag<T = Int>` used to arrive here bare
            # and raise an internal compiler error.
            filled = self._fill_default_type_args(struct_name, [])
            if filled:
                struct_name = self._ensure_monomorphized_struct(
                    expr.struct_name, filled)

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

        # Get field types for Copy handling (use namespace)
        field_types = self.namespace.get_struct_fields(struct_name) or {}

        # Create a map from field name to value, handling Copy
        field_values = {}
        for field_name, value_expr in expr.field_inits:
            value = self._generate_expression(value_expr)

            # Check if this field needs copy() called
            field_type = field_types.get(field_name)

            # Coerce an integer value to the field's EXACT fixed width (design 65
            # followup). A bare integer literal is materialized at the platform
            # word (i64 on a hosted build), but a struct field has the field's
            # concrete layout — an `Int8` field is an i8 slot — so inserting the
            # i64 literal ICE'd ("Can only insert i8 ... got i64"). Retype the
            # literal to the field width (an out-of-range literal is the standard
            # range error, not an ICE); widen/narrow a runtime int to fit.
            if field_type is not None:
                value = self._coerce_int_to_field(value, field_type, value_expr)

            if field_type and self._needs_copy_for_struct_init(value_expr, field_type):
                # An opt-encoded destination field is `T?` while the value is
                # the bare payload — the wrap happens below, so the copy glue
                # must be driven by the PAYLOAD's type, not the field's.
                # `_generate_copy_for_dest` is that rule. It was written here as
                # a design-124 special case (only a frame-field read
                # `self.name!` got the payload type), but the hazard belongs to
                # the DESTINATION, so an ordinary `Holder(o: s)` on a
                # `String?` field hit it just the same (DF-151c).
                value = self._generate_copy_for_dest(value, field_type)

            # DF-218f: a bare payload written into a `Result`-typed field. The
            # optional wrap two blocks down is decided from the LLVM SHAPE,
            # which cannot see this one — a Result is an enum, not `{i1, T}` —
            # so the typechecker's mark is what carries it, and the shared
            # builder applies the `Result<T?, E>` double wrap in order.
            if getattr(value_expr, 'autowrap_to_result', None) is not None:
                value = self._maybe_autowrap_optional(value_expr, value)

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

        The list is exactly `_is_owned_temporary`'s borrows minus the indexed
        forms: an identifier, `self`, and a field of one of those. An
        `ArrayIndex`/`TupleIndex` base is deliberately absent — addressing one
        emits its own bounds check, and whether that is the same check the value
        read emits is a question this brief does not need to answer.
        """
        if isinstance(expr, SelfExpr):
            return "self" in self.variables
        if isinstance(expr, Identifier):
            return (expr.name in self.variables
                    or self._static_global(expr) is not None)
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
        if isinstance(obj, (Identifier, SelfExpr, MemberAccess)):
            if not self._addressable_place(obj):
                return None
            base_ptr = self._get_lvalue_pointer(obj)
            # An identifier bound to a POINTER (a by-pointer receiver forwarded
            # onward, a `Box`) is storage holding storage: step through once, so
            # the GEP lands on the struct rather than on the slot holding it.
            pointee = base_ptr.type.pointee
            if isinstance(pointee, ir.PointerType):
                base_ptr = self.builder.load(base_ptr, name="deref_ptr")
        elif isinstance(obj, (FunctionCall, MethodCall, StructInit, EnumInit,
                              TupleLiteral, ArrayLiteral, MapLiteral,
                              SetLiteral)):
            # An owned temporary owes `_register_stmt_temp` the whole value, so
            # it takes the value path where that registration lives.
            return None
        else:
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

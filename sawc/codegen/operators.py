"""
Operator code generation for the Saw code generator.

This module provides mixin methods for generating LLVM IR code for binary
and unary operators, including arithmetic, comparison, and logical operators.

Usage:
    class CodeGenerator(OperatorsMixin, ...):
        pass
"""

from llvmlite import ir
from ast_nodes import BinaryOp, UnaryOp, MoveExpr, ReferenceExpr, CastExpr, TypeKind, Identifier, MemberAccess, ArrayIndex, SelfExpr, SawType
from .mangle import mangle_named

# Unsigned integer kinds: everything else that is an integer is treated as
# signed (the codebase default -- comparisons use icmp_signed, division sdiv).
_UNSIGNED_INT_KINDS = {
    TypeKind.UINT, TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64
}


class OperatorsMixin:
    """Mixin providing operator generation methods for CodeGenerator.

    Methods:
        _generate_binary_op: Generate code for binary operations
        _generate_logical_and: Generate short-circuit && evaluation
        _generate_logical_or: Generate short-circuit || evaluation
        _generate_unary_op: Generate code for unary operations
        _generate_move_expr: Generate code for move expressions
        _generate_cast_expr: Generate code for type casts
    """

    def _emit_panic(self, message: str):
        """Emit a runtime panic via the saw_panic seam, then terminate the block.

        The single lowering for every compiler-emitted panic (div/mod by zero,
        force-unwrap of None, try! on Err, ...): build the constant message as a
        private byte global (exact text preserved — panic tests match on it) and
        call saw_panic(ptr, len), which is noreturn. The `unreachable` terminates
        the block. The caller must have positioned the builder in the panicking
        block. In the hosted profile saw_panic prints the message and aborts; in
        the freestanding profile the environment provides saw_panic.
        """
        msg = message if message.endswith("\n") else message + "\n"
        encoded = msg.encode('utf-8')
        n = len(encoded)
        arr_type = ir.ArrayType(ir.IntType(8), n)
        panic_global = ir.GlobalVariable(self.module, arr_type,
                                         name=f".panic_msg.{self.string_counter}")
        self.string_counter += 1
        panic_global.global_constant = True
        panic_global.initializer = ir.Constant(arr_type, bytearray(encoded))
        panic_global.linkage = 'private'
        zero = ir.Constant(ir.IntType(32), 0)
        panic_ptr = self.builder.gep(panic_global, [zero, zero], inbounds=True)
        # saw_panic takes a platform-width length (design 47).
        self.builder.call(self.functions["saw_panic"],
                          [panic_ptr, ir.Constant(self.int_type, n)])
        self.builder.unreachable()

    def _check_divisor_nonzero(self, divisor):
        """Guard an integer division/modulo: panic if `divisor` is zero.

        Emits `if divisor == 0 { panic } else { continue }` and leaves the
        builder positioned in the continue block, where the raw sdiv/srem is
        then generated. Needed because arm64 does not trap on integer
        divide-by-zero, so without this the program silently returns garbage.
        (INT_MIN / -1 overflow is intentionally NOT handled here; integer
        overflow semantics are an open spec question — see todo_jul26.md #5/#7.)
        """
        zero = ir.Constant(divisor.type, 0)
        is_zero = self.builder.icmp_signed('==', divisor, zero, name="divzero_check")
        func = self.builder.function
        panic_bb = func.append_basic_block(name="div_panic")
        cont_bb = func.append_basic_block(name="div_cont")
        self.builder.cbranch(is_zero, panic_bb, cont_bb)

        self.builder.position_at_end(panic_bb)
        self._emit_panic("panic: division by zero")

        self.builder.position_at_end(cont_bb)

    def _int_is_signed(self, expr) -> bool:
        """Whether `expr`'s (integer) type is signed.

        Reads the typechecker annotation, resolving type aliases first. Anything
        not explicitly one of the unsigned kinds -- including an unannotated
        expression -- is treated as signed, matching the codebase's
        signed-centric integer handling (comparisons use icmp_signed, division
        sdiv). Only genuine unsigned arithmetic (`let u: UInt = ...`), which is
        reliably annotated, needs the unsigned intrinsic; deferring to signed
        elsewhere is both safe and correct for `Int`. This intentionally does NOT
        use the fail-loud `_expr_type`: a missing annotation must not turn a
        signedness hint into a hard compile error.
        """
        resolved = getattr(expr, 'resolved_type', None)
        if resolved is None:
            return True
        if self.type_param_context:
            resolved = resolved.substitute(self.type_param_context)
        resolved = self._resolve_type_alias(resolved)
        return resolved.kind not in _UNSIGNED_INT_KINDS

    def _overflow_intrinsic(self, op: str, signed: bool, width: int):
        """Get (declaring on first use) the LLVM checked-arithmetic intrinsic
        for `op` at the given signedness and bit width, e.g.
        `llvm.sadd.with.overflow.i64`. Returns {iN, i1}: (result, overflow flag).
        """
        base = {'+': 'add', '-': 'sub', '*': 'mul'}[op]
        prefix = 's' if signed else 'u'
        name = f"llvm.{prefix}{base}.with.overflow.i{width}"
        cache = getattr(self, '_overflow_intrinsics', None)
        if cache is None:
            cache = self._overflow_intrinsics = {}
        if name in cache:
            return cache[name]
        int_ty = ir.IntType(width)
        ret_ty = ir.LiteralStructType([int_ty, ir.IntType(1)])
        fn = ir.Function(self.module, ir.FunctionType(ret_ty, [int_ty, int_ty]),
                         name=name)
        cache[name] = fn
        return fn

    def _checked_arith(self, op: str, left, right, signed: bool):
        """Emit an overflow-checked integer add/sub/mul (design 31).

        Uses the `llvm.{s,u}{add,sub,mul}.with.overflow` intrinsic and branches
        to the standard panic seam ("integer overflow") when the overflow flag is
        set, mirroring the div-by-zero panic-block pattern. Leaves the builder in
        the non-overflowing continuation block and returns the wrapped result.
        """
        intrinsic = self._overflow_intrinsic(op, signed, left.type.width)
        agg = self.builder.call(intrinsic, [left, right], name="ovf")
        result = self.builder.extract_value(agg, 0, name="ovf_val")
        flag = self.builder.extract_value(agg, 1, name="ovf_flag")

        func = self.builder.function
        panic_bb = func.append_basic_block(name="ovf_panic")
        cont_bb = func.append_basic_block(name="ovf_cont")
        self.builder.cbranch(flag, panic_bb, cont_bb)

        self.builder.position_at_end(panic_bb)
        self._emit_panic("panic: integer overflow")

        self.builder.position_at_end(cont_bb)
        return result

    def _check_div_no_overflow(self, dividend, divisor):
        """Guard a *signed* division/modulo against the `INT_MIN / -1` overflow.

        `INT_MIN / -1` is +2^(w-1), unrepresentable in a w-bit signed integer (C
        UB, and a hardware trap on some targets). Panics with "integer overflow"
        for both `/` and `%` (see design 31: `%`'s mathematically-zero result is
        defined via the same panic for consistency with division). Emitted beside
        the existing zero-divisor check; leaves the builder in the continue block.
        """
        ty = dividend.type
        int_min = ir.Constant(ty, -(1 << (ty.width - 1)))
        neg_one = ir.Constant(ty, -1)
        is_min = self.builder.icmp_signed('==', dividend, int_min, name="divovf_min")
        is_neg1 = self.builder.icmp_signed('==', divisor, neg_one, name="divovf_neg1")
        is_ovf = self.builder.and_(is_min, is_neg1, name="divovf_check")

        func = self.builder.function
        panic_bb = func.append_basic_block(name="divovf_panic")
        cont_bb = func.append_basic_block(name="divovf_cont")
        self.builder.cbranch(is_ovf, panic_bb, cont_bb)

        self.builder.position_at_end(panic_bb)
        self._emit_panic("panic: integer overflow")

        self.builder.position_at_end(cont_bb)

    @staticmethod
    def _reconcile_int_width(builder, value, target_type):
        """Adapt an integer `value` to `target_type`'s width via trunc/zext.

        The typechecker admits mixed integer *kinds* in a bitwise/shift op (it
        returns the left operand's type); LLVM `and`/`or`/`xor`/`shl` require both
        operands at the same width, so the right operand is brought to the left's.
        """
        if value.type.width == target_type.width:
            return value
        if value.type.width > target_type.width:
            return builder.trunc(value, target_type, name="bwadj")
        return builder.zext(value, target_type, name="bwadj")

    def _emit_bitwise(self, op: str, left, right):
        """Bitwise AND/OR/XOR on integers (design 50)."""
        right = self._reconcile_int_width(self.builder, right, left.type)
        if op == '&':
            return self.builder.and_(left, right, name="andtmp")
        if op == '|':
            return self.builder.or_(left, right, name="ortmp")
        return self.builder.xor(left, right, name="xortmp")

    def _emit_shift(self, op: str, left, right, signed: bool):
        """Emit `<<` / `>>` with a runtime range check (design 50).

        A shift amount that is negative or >= the left operand's bit width panics
        with "shift out of range" (the checked-arithmetic house rule; Rust-debug
        precedent). Both cases fold into one *unsigned* `amount >= width` compare:
        a negative signed amount reinterpreted as unsigned is enormous, so it is
        caught too. The compare runs at the amount's own width *before* narrowing,
        so a large amount can't be truncated down into the legal range first.
        `>>` lowers to `ashr` (arithmetic) for a signed left operand, `lshr`
        (logical) for an unsigned one.
        """
        width = left.type.width
        wconst = ir.Constant(right.type, width)
        oob = self.builder.icmp_unsigned('>=', right, wconst, name="shift_oob")

        func = self.builder.function
        panic_bb = func.append_basic_block(name="shift_panic")
        cont_bb = func.append_basic_block(name="shift_cont")
        self.builder.cbranch(oob, panic_bb, cont_bb)

        self.builder.position_at_end(panic_bb)
        self._emit_panic("panic: shift out of range")

        self.builder.position_at_end(cont_bb)
        # In-range now (amount < width <= 64): safe to narrow to the shift width.
        amt = self._reconcile_int_width(self.builder, right, left.type)
        if op == '<<':
            return self.builder.shl(left, amt, name="shltmp")
        if signed:
            return self.builder.ashr(left, amt, name="ashrtmp")
        return self.builder.lshr(left, amt, name="lshrtmp")

    def _generate_binary_op(self, expr: BinaryOp):
        """Generate code for binary operations.

        Handles arithmetic (+, -, *, /, %), wrapping arithmetic (&+, &-, &*),
        bitwise (&, |, ^, <<, >>), comparison (==, !=, <, >, <=, >=), and
        logical (&&, ||) operators.
        """
        # Handle short-circuit logical operators specially
        if expr.op == '&&':
            return self._generate_logical_and(expr)
        elif expr.op == '||':
            return self._generate_logical_or(expr)

        left = self._generate_expression(expr.left)
        right = self._generate_expression(expr.right)

        # Check if we're dealing with floats
        is_float = isinstance(left.type, ir.DoubleType)

        # Wrapping arithmetic (design 31): defined two's-complement wrap, no
        # overflow check. Integer-only (enforced by the typechecker), so no
        # float/pointer sub-cases here.
        if expr.op == '&+':
            return self.builder.add(left, right, name="wrapaddtmp")
        elif expr.op == '&-':
            return self.builder.sub(left, right, name="wrapsubtmp")
        elif expr.op == '&*':
            return self.builder.mul(left, right, name="wrapmultmp")

        # Bitwise AND/OR/XOR and shifts (design 50). Integer-only (enforced by the
        # typechecker). `>>` is arithmetic on a signed left operand, logical on an
        # unsigned one; shifts range-check the amount at runtime.
        if expr.op in ('&', '|', '^'):
            return self._emit_bitwise(expr.op, left, right)
        elif expr.op in ('<<', '>>'):
            return self._emit_shift(expr.op, left, right,
                                    self._int_is_signed(expr.left))

        if expr.op == '+':
            if isinstance(left.type, ir.PointerType):
                # Pointer arithmetic: ptr + offset
                return self.builder.gep(left, [right], name="ptr_add")
            if is_float:
                return self.builder.fadd(left, right, name="addtmp")
            # Integer add: overflow panics (design 31).
            return self._checked_arith('+', left, right, self._int_is_signed(expr.left))

        elif expr.op == '-':
            if isinstance(left.type, ir.PointerType):
                # Pointer arithmetic: ptr - offset (negate offset and add)
                neg_right = self.builder.neg(right, name="neg_offset")
                return self.builder.gep(left, [neg_right], name="ptr_sub")
            if is_float:
                return self.builder.fsub(left, right, name="subtmp")
            return self._checked_arith('-', left, right, self._int_is_signed(expr.left))

        elif expr.op == '*':
            if is_float:
                return self.builder.fmul(left, right, name="multmp")
            return self._checked_arith('*', left, right, self._int_is_signed(expr.left))

        elif expr.op == '/':
            if is_float:
                # Float division keeps IEEE inf/nan semantics (untouched).
                return self.builder.fdiv(left, right, name="divtmp")
            # Integer division: panic on a zero divisor instead of returning
            # garbage (arm64 does not trap). Signed division also panics on the
            # INT_MIN / -1 overflow and uses sdiv; unsigned division has no such
            # overflow and must use udiv (design 41 item 0 / design 40 L6 sidecar
            # -- an unsigned operand with the high bit set gives the wrong result
            # under sdiv).
            self._check_divisor_nonzero(right)
            if self._int_is_signed(expr.left):
                self._check_div_no_overflow(left, right)
                return self.builder.sdiv(left, right, name="divtmp")
            return self.builder.udiv(left, right, name="udivtmp")

        elif expr.op == '%':
            # Modulo only works on integers; same zero-divisor panic as /, and
            # the same signed/unsigned split: srem (with the INT_MIN / -1 overflow
            # panic) for signed operands, urem for unsigned.
            self._check_divisor_nonzero(right)
            if self._int_is_signed(expr.left):
                self._check_div_no_overflow(left, right)
                return self.builder.srem(left, right, name="modtmp")
            return self.builder.urem(left, right, name="umodtmp")

        elif expr.op == '==':
            # Equality (design 32): lower via the recursive Equatable helper.
            # Primitives fold to icmp/fcmp; String/struct/enum route to content /
            # memberwise / payload-deep comparison.
            return self._emit_equals(left, right, self._equality_operand_type(expr))

        elif expr.op == '!=':
            # `!=` is always the negation of `==` (design 32).
            eq = self._emit_equals(left, right, self._equality_operand_type(expr))
            return self.builder.not_(eq, name="netmp")

        elif expr.op == '<':
            if is_float:
                return self.builder.fcmp_ordered('<', left, right, name="lttmp")
            return self.builder.icmp_signed('<', left, right, name="lttmp")

        elif expr.op == '>':
            if is_float:
                return self.builder.fcmp_ordered('>', left, right, name="gttmp")
            return self.builder.icmp_signed('>', left, right, name="gttmp")

        elif expr.op == '<=':
            if is_float:
                return self.builder.fcmp_ordered('<=', left, right, name="letmp")
            return self.builder.icmp_signed('<=', left, right, name="letmp")

        elif expr.op == '>=':
            if is_float:
                return self.builder.fcmp_ordered('>=', left, right, name="getmp")
            return self.builder.icmp_signed('>=', left, right, name="getmp")

        else:
            raise ValueError(f"Unknown binary operator: {expr.op}")

    # =========================================================================
    # Equality lowering (design 32)
    #
    # `_emit_equals` is the single recursive helper that lowers `a == b` for any
    # Equatable type. It reads two already-materialized LLVM values plus the
    # operand's Saw type, so it never "moves" or consumes anything. `!=` negates
    # its result. Primitives fold to icmp/fcmp; String calls its content-equals
    # runtime; a struct dispatches to its (synthesized or custom) equals method,
    # or compares memberwise inline when it auto-conforms; an enum compares tag
    # then active-variant payload fields (recursively). Tuples compare
    # element-by-element (design 32 item 8).
    # =========================================================================

    def _equality_operand_type(self, expr: BinaryOp):
        """The Saw type an `==`/`!=` operand was checked at, substituted for the
        active monomorphization. Returns None for compiler-synthesized operands
        that carry no annotation (handled by the LLVM-type fallback)."""
        st = getattr(expr.left, 'resolved_type', None)
        if st is None:
            st = getattr(expr.right, 'resolved_type', None)
        if st is not None and self.type_param_context:
            st = st.substitute(self.type_param_context)
        return st

    def _emit_equals(self, left, right, saw_type):
        """Emit an i1 that is true iff `left == right`, recursively (design 32)."""
        st = self._resolve_type_alias(saw_type) if saw_type is not None else None
        lt = left.type

        # Float keeps IEEE semantics (NaN != NaN via ordered compare).
        if isinstance(lt, ir.DoubleType):
            return self.builder.fcmp_ordered('==', left, right, name="feq")

        if st is not None:
            k = st.kind
            if k == TypeKind.STRING:
                return self._emit_string_equals(left, right)
            if k == TypeKind.TUPLE:
                return self._emit_tuple_equals(left, right, st)
            if k == TypeKind.OPTIONAL:
                return self._emit_optional_equals(left, right, st)
            if k == TypeKind.ARRAY:
                return self._emit_array_equals(left, right, st)
            if k == TypeKind.STRUCT and not isinstance(lt, ir.IntType):
                return self._emit_struct_equals(left, right, st)
            if k == TypeKind.ENUM and isinstance(lt, ir.LiteralStructType):
                return self._emit_enum_deep_equals(left, right, st)

        # Primitives (integers, Bool) and payload-free enums (an i32 tag).
        if isinstance(lt, ir.IntType):
            return self.builder.icmp_signed('==', left, right, name="ieq")

        # Fallback for values reaching here without a Saw type (compiler-
        # synthesized comparisons): an enum-shaped {i32, [N x i8]} value compares
        # tags (the historical behavior); a bare pointer compares by identity.
        if (isinstance(lt, ir.LiteralStructType) and len(lt.elements) == 2
                and isinstance(lt.elements[0], ir.IntType)
                and lt.elements[0].width == 32):
            l_tag = self.builder.extract_value(left, 0, name="l_tag")
            r_tag = self.builder.extract_value(right, 0, name="r_tag")
            return self.builder.icmp_signed('==', l_tag, r_tag, name="tageq")
        if isinstance(lt, ir.PointerType):
            return self.builder.icmp_signed('==', left, right, name="peq")

        raise ValueError(f"cannot lower `==` for LLVM type {lt}")

    def _emit_string_equals(self, left, right):
        """String `==` is content equality via the stdlib `String.equals`."""
        fn = self.functions.get(self._mangle_method_name("String", "equals"))
        if fn is None:
            # String.equals not linked (String stdlib absent): fall back to
            # pointer identity so codegen stays total.
            return self.builder.icmp_signed('==', left, right, name="streq_ptr")
        return self.builder.call(fn, [left, right], name="streq")

    def _emit_tuple_equals(self, left, right, saw_type):
        """Tuple `==`: conjunction of element-wise `==` (design 32 item 8)."""
        result = ir.Constant(ir.IntType(1), 1)
        elems = saw_type.element_types or []
        for i, elem_type in enumerate(elems):
            le = self.builder.extract_value(left, i, name=f"l_e{i}")
            re = self.builder.extract_value(right, i, name=f"r_e{i}")
            cmp = self._emit_equals(le, re, elem_type)
            result = self.builder.and_(result, cmp, name="tup_and")
        return result

    def _emit_struct_equals(self, left, right, saw_type):
        """Struct `==`: dispatch to the type's `equals` method (synthesized or
        custom) when one exists, else compare fields inline (auto-conform POD)."""
        base = self._type_method_base(saw_type)
        mangled = self._mangle_method_name(base, "equals") if base else None
        if mangled is not None and mangled in self.functions:
            return self.builder.call(self.functions[mangled], [left, right],
                                     name="eq_call")
        return self._emit_memberwise_equals(left, right, saw_type)

    def _emit_memberwise_equals(self, left, right, saw_type):
        """Field-by-field `==` over a struct value, ANDed together."""
        key = self._type_method_base(saw_type)
        llvm_struct_type, field_order = self.struct_types[key]
        base_fields = self.namespace.get_struct_fields(saw_type.struct_name) or {}
        # Substitute type params for a monomorphized generic struct.
        subst = {}
        struct_sym = self.namespace._lookup_struct_deep(saw_type.struct_name)
        if struct_sym and saw_type.type_args:
            for tp, arg in zip(struct_sym.type_params, saw_type.type_args):
                subst[tp.name] = arg
        result = ir.Constant(ir.IntType(1), 1)
        for i, fname in enumerate(field_order):
            ftype = base_fields.get(fname)
            if ftype is not None and subst:
                ftype = ftype.substitute(subst)
            lf = self.builder.extract_value(left, i, name=f"l_{fname}")
            rf = self.builder.extract_value(right, i, name=f"r_{fname}")
            cmp = self._emit_equals(lf, rf, ftype)
            result = self.builder.and_(result, cmp, name="mem_and")
        return result

    def _emit_optional_equals(self, left, right, saw_type):
        """Optional `==` (design 40 item 4): None==None true, None vs Some
        false, payload-deep otherwise. Represented as `{ i1 is_some, T }`. The
        payload is compared only when both sides are Some, so a None slot's
        undefined payload is never touched (matters for String/struct inners
        whose comparison dereferences)."""
        i1 = ir.IntType(1)
        l_some = self.builder.extract_value(left, 0, name="l_some")
        r_some = self.builder.extract_value(right, 0, name="r_some")
        flags_eq = self.builder.icmp_unsigned('==', l_some, r_some, name="opt_flags_eq")
        both_some = self.builder.and_(l_some, r_some, name="opt_both_some")

        func = self.builder.function
        entry_bb = self.builder.block
        payload_bb = func.append_basic_block("opt_eq_payload")
        merge_bb = func.append_basic_block("opt_eq_merge")
        # Both Some -> compare payloads; else the flag equality is the answer
        # (both None -> true, one None -> false).
        self.builder.cbranch(both_some, payload_bb, merge_bb)

        self.builder.position_at_end(payload_bb)
        l_val = self.builder.extract_value(left, 1, name="l_val")
        r_val = self.builder.extract_value(right, 1, name="r_val")
        payload_eq = self._emit_equals(l_val, r_val, saw_type.inner_type)
        # _emit_equals may have appended blocks; branch from wherever it landed.
        payload_end_bb = self.builder.block
        self.builder.branch(merge_bb)

        self.builder.position_at_end(merge_bb)
        phi = self.builder.phi(i1, name="opt_eq")
        phi.add_incoming(flags_eq, entry_bb)
        phi.add_incoming(payload_eq, payload_end_bb)
        return phi

    def _emit_array_equals(self, left, right, saw_type):
        """Fixed-array `==` (design 40 item 4): the conjunction of element-wise
        `==` over all `N` slots (`[T; N]`, fully initialized)."""
        elem_type = saw_type.array_element_type
        n = saw_type.array_size or 0
        result = ir.Constant(ir.IntType(1), 1)
        for i in range(n):
            le = self.builder.extract_value(left, i, name=f"l_a{i}")
            re = self.builder.extract_value(right, i, name=f"r_a{i}")
            cmp = self._emit_equals(le, re, elem_type)
            result = self.builder.and_(result, cmp, name="arr_and")
        return result

    def _emit_enum_deep_equals(self, left, right, saw_type):
        """Enum `==`: equal tags, then the active variant's payload fields
        compared recursively (design 32). Payload-free variants are true once
        the tags match."""
        mangled = mangle_named(saw_type.enum_name, saw_type.type_args)
        llvm_enum_type, variant_tags, variant_info = self.enum_types[mangled]
        i1 = ir.IntType(1)
        i32 = ir.IntType(32)

        left_tag = self.builder.extract_value(left, 0, name="l_tag")
        right_tag = self.builder.extract_value(right, 0, name="r_tag")
        tags_eq = self.builder.icmp_signed('==', left_tag, right_tag, name="tags_eq")

        func = self.builder.function
        entry_bb = self.builder.block
        payload_bb = func.append_basic_block("eq_payload")
        merge_bb = func.append_basic_block("eq_merge")
        # Tags differ -> false (skip payload); tags equal -> compare payload.
        self.builder.cbranch(tags_eq, payload_bb, merge_bb)

        self.builder.position_at_end(payload_bb)
        true_bb = func.append_basic_block("eq_payload_free")
        switch = self.builder.switch(left_tag, true_bb)
        payload_array_type = llvm_enum_type.elements[1]
        incoming = []
        for variant_name, fields in variant_info.items():
            if not fields:
                continue  # payload-free variant -> default (true) block
            arm_bb = func.append_basic_block(f"eq_{variant_name}")
            switch.add_case(ir.Constant(i32, variant_tags[variant_name]), arm_bb)
            self.builder.position_at_end(arm_bb)

            l_payload = self.builder.extract_value(left, 1, name="l_pl")
            r_payload = self.builder.extract_value(right, 1, name="r_pl")
            param_struct_type = ir.LiteralStructType(
                [self._get_llvm_type(t) for _, t in fields])
            l_alloca = self._entry_alloca(payload_array_type, name="l_pl_slot")
            self.builder.store(l_payload, l_alloca)
            r_alloca = self._entry_alloca(payload_array_type, name="r_pl_slot")
            self.builder.store(r_payload, r_alloca)
            l_sp = self.builder.bitcast(l_alloca, ir.PointerType(param_struct_type),
                                        name="l_sp")
            r_sp = self.builder.bitcast(r_alloca, ir.PointerType(param_struct_type),
                                        name="r_sp")
            arm_result = ir.Constant(i1, 1)
            for idx, (fname, ftype) in enumerate(fields):
                l_fp = self.builder.gep(l_sp, [ir.Constant(i32, 0),
                                               ir.Constant(i32, idx)], inbounds=True)
                r_fp = self.builder.gep(r_sp, [ir.Constant(i32, 0),
                                               ir.Constant(i32, idx)], inbounds=True)
                lf = self.builder.load(l_fp, name=f"l_{fname}")
                rf = self.builder.load(r_fp, name=f"r_{fname}")
                fcmp = self._emit_equals(lf, rf, ftype)
                arm_result = self.builder.and_(arm_result, fcmp, name="pl_and")
            arm_end = self.builder.block
            self.builder.branch(merge_bb)
            incoming.append((arm_result, arm_end))

        self.builder.position_at_end(true_bb)
        self.builder.branch(merge_bb)

        self.builder.position_at_end(merge_bb)
        phi = self.builder.phi(i1, name="enum_eq")
        phi.add_incoming(ir.Constant(i1, 0), entry_bb)   # tags differ
        phi.add_incoming(ir.Constant(i1, 1), true_bb)    # payload-free, equal tag
        for val, blk in incoming:
            phi.add_incoming(val, blk)
        return phi

    def _generate_logical_and(self, expr: BinaryOp):
        """Generate short-circuit && evaluation.

        left && right:
        - Evaluate left
        - If left is false, result is false (don't evaluate right)
        - If left is true, result is value of right
        """
        func = self.builder.block.function

        # Create blocks
        eval_right_block = func.append_basic_block(name="and_right")
        merge_block = func.append_basic_block(name="and_merge")

        # Evaluate left operand
        left = self._generate_expression(expr.left)
        left_block = self.builder.block

        # Branch: if left is false, go to merge with false; else evaluate right
        self.builder.cbranch(left, eval_right_block, merge_block)

        # Evaluate right operand
        self.builder.position_at_end(eval_right_block)
        right = self._generate_expression(expr.right)
        right_block = self.builder.block
        self.builder.branch(merge_block)

        # Merge: phi node selects result
        self.builder.position_at_end(merge_block)
        phi = self.builder.phi(ir.IntType(1), name="and_result")
        phi.add_incoming(ir.Constant(ir.IntType(1), 0), left_block)  # false from left
        phi.add_incoming(right, right_block)  # right value if left was true

        return phi

    def _generate_logical_or(self, expr: BinaryOp):
        """Generate short-circuit || evaluation.

        left || right:
        - Evaluate left
        - If left is true, result is true (don't evaluate right)
        - If left is false, result is value of right
        """
        func = self.builder.block.function

        # Create blocks
        eval_right_block = func.append_basic_block(name="or_right")
        merge_block = func.append_basic_block(name="or_merge")

        # Evaluate left operand
        left = self._generate_expression(expr.left)
        left_block = self.builder.block

        # Branch: if left is true, go to merge with true; else evaluate right
        self.builder.cbranch(left, merge_block, eval_right_block)

        # Evaluate right operand
        self.builder.position_at_end(eval_right_block)
        right = self._generate_expression(expr.right)
        right_block = self.builder.block
        self.builder.branch(merge_block)

        # Merge: phi node selects result
        self.builder.position_at_end(merge_block)
        phi = self.builder.phi(ir.IntType(1), name="or_result")
        phi.add_incoming(ir.Constant(ir.IntType(1), 1), left_block)  # true from left
        phi.add_incoming(right, right_block)  # right value if left was false

        return phi

    def _generate_unary_op(self, expr: UnaryOp):
        """Generate code for unary operations (-, not)."""
        operand = self._generate_expression(expr.operand)

        if expr.op == '-':
            if isinstance(operand.type, ir.DoubleType):
                return self.builder.fneg(operand, name="negtmp")
            # Integer negation is `0 - x`; negating the signed minimum overflows
            # (its magnitude is unrepresentable) and panics (design 31). Unary `-`
            # is signed-only (typechecker allows Int/Float), so a signed checked
            # subtract is exactly right.
            zero = ir.Constant(operand.type, 0)
            return self._checked_arith('-', zero, operand, True)

        elif expr.op == 'not':
            # Logical NOT: flip the boolean (XOR with 1)
            return self.builder.xor(operand, ir.Constant(ir.IntType(1), 1), name="nottmp")

        elif expr.op == '~':
            # Bitwise complement (design 50): flip every bit (XOR with all-ones).
            # `builder.not_` emits `xor value, -1` at the operand's integer width.
            return self.builder.not_(operand, name="bnottmp")

        else:
            raise ValueError(f"Unknown unary operator: {expr.op}")

    def _generate_move_expr(self, expr: MoveExpr):
        """Generate code for move expression - transfers ownership without copying."""
        var_name = expr.variable
        if var_name not in self.variables:
            raise ValueError(f"Undefined variable: {var_name}")

        # Load the value
        value = self.builder.load(self.variables[var_name], name=f"{var_name}_moved")

        # Mark as moved - skip deinit and prevent further use.
        self.moved_variables.add(var_name)
        # Clear the runtime drop flag (design 42): on a path that reaches this
        # `move`, the binding's ownership has left, so its scope-exit deinit must
        # NOT fire. A binding moved only here (a conditional move) still drops on
        # the paths that skip this store, because the flag stays 1 there.
        flag = self.drop_flags.get(var_name)
        if flag is not None:
            self.builder.store(ir.Constant(ir.IntType(1), 0), flag)

        return value

    def _generate_reference_expr(self, expr: ReferenceExpr):
        """Generate code for reference expression: &expr or &var expr.

        Returns a pointer to the referenced value.
        """
        inner_expr = expr.expr

        if isinstance(inner_expr, Identifier):
            # Reference to a variable - return its alloca
            var_name = inner_expr.name
            if var_name not in self.variables:
                # `&STATIC` (design 41): an immutable lend of a module static
                # yields a pointer to its global.
                if var_name in self.static_globals:
                    return self.static_globals[var_name]
                raise ValueError(f"Undefined variable: {var_name}")
            return self.variables[var_name]
        elif isinstance(inner_expr, SelfExpr):
            # Reference to self - return self's alloca/pointer
            if "self" not in self.variables:
                raise ValueError("'self' not available in this context")
            return self.variables["self"]
        elif isinstance(inner_expr, MemberAccess):
            # Reference to struct field - get GEP pointer
            return self._get_member_pointer(inner_expr)
        elif isinstance(inner_expr, ArrayIndex):
            # Reference to array/pointer element - get a stable GEP pointer
            return self._get_array_element_pointer(inner_expr)
        else:
            # For other expressions, evaluate and store in a temporary
            value = self._generate_expression(inner_expr)
            temp = self._entry_alloca(value.type, name="ref_temp")
            self.builder.store(value, temp)
            return temp

    def _get_array_element_pointer(self, expr: ArrayIndex):
        """Return a stable pointer to an array or pointer element, for `&arr[i]`.

        Mirrors the lvalue logic used by array-element assignment: obtain a
        pointer to the container's storage, then GEP into it -- so the reference
        aliases the real element rather than a materialized copy.
        """
        index_val = self._generate_expression(expr.index)
        container_expr = expr.array_expr

        # Obtain a pointer to the container's storage.
        if isinstance(container_expr, Identifier):
            if container_expr.name not in self.variables:
                raise ValueError(f"Undefined variable: {container_expr.name}")
            container_ptr = self.variables[container_expr.name]
        elif isinstance(container_expr, SelfExpr):
            container_ptr = self.variables["self"]
        elif isinstance(container_expr, MemberAccess):
            container_ptr = self._get_member_pointer(container_expr)
        elif isinstance(container_expr, ArrayIndex):
            container_ptr = self._get_array_element_pointer(container_expr)
        else:
            # Fallback: materialize the container (won't propagate mutations).
            container_val = self._generate_expression(container_expr)
            container_ptr = self._entry_alloca(container_val.type, name="arr_tmp")
            self.builder.store(container_val, container_ptr)

        pointee = container_ptr.type.pointee
        if isinstance(pointee, ir.ArrayType):
            zero = ir.Constant(ir.IntType(64), 0)
            return self.builder.gep(container_ptr, [zero, index_val], name="elem_ptr")
        elif isinstance(pointee, ir.PointerType):
            # The variable holds a pointer value; load it, then offset.
            base = self.builder.load(container_ptr, name="ptr_base")
            return self.builder.gep(base, [index_val], name="ptr_elem")
        else:
            raise ValueError(
                f"Cannot take reference to element of non-array type: {pointee}")

    def _generate_cast_expr(self, expr: CastExpr):
        """Generate code for type cast: expr as Type"""
        value = self._generate_expression(expr.expr)
        from_saw_type = self._expr_type(expr.expr)
        to_type = expr.target_type
        to_llvm = self._get_llvm_type(to_type)

        # Get actual LLVM bit widths from the values (more reliable than Saw types
        # because integer literals are always i64 in LLVM)
        if isinstance(value.type, ir.IntType) and isinstance(to_llvm, ir.IntType):
            from_bits = value.type.width
            to_bits = to_llvm.width

            # Determine signedness from Saw type
            signed_kinds = {TypeKind.INT, TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64}
            from_signed = from_saw_type and from_saw_type.kind in signed_kinds

            if to_bits > from_bits:
                # Widening - use sign extension or zero extension based on source signedness
                if from_signed:
                    return self.builder.sext(value, to_llvm, name="sext")
                else:
                    return self.builder.zext(value, to_llvm, name="zext")
            elif to_bits < from_bits:
                # Narrowing - truncate
                return self.builder.trunc(value, to_llvm, name="trunc")
            else:
                # Same size - no conversion needed
                return value

        # Pointer to pointer conversion (also covers reference -> pointer, since a
        # `&T` reference lowers to an LLVM pointer value — design 42 slab regions).
        if isinstance(value.type, ir.PointerType) and isinstance(to_llvm, ir.PointerType):
            return self.builder.bitcast(value, to_llvm, name="ptrcast")

        # Pointer <-> integer address round-trip (design 42 slab free-list).
        if isinstance(value.type, ir.PointerType) and isinstance(to_llvm, ir.IntType):
            return self.builder.ptrtoint(value, to_llvm, name="ptrtoint")
        if isinstance(value.type, ir.IntType) and isinstance(to_llvm, ir.PointerType):
            return self.builder.inttoptr(value, to_llvm, name="inttoptr")

        raise ValueError(f"Cannot cast from {value.type} to {to_llvm}")

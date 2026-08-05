"""
Operator code generation for the Saw code generator.

This module provides mixin methods for generating LLVM IR code for binary
and unary operators, including arithmetic, comparison, and logical operators.

Usage:
    class CodeGenerator(OperatorsMixin, ...):
        pass
"""

from llvmlite import ir
from ast_nodes import BinaryOp, UnaryOp, MoveExpr, ReferenceExpr, CastExpr, TypeKind, Identifier, MemberAccess, ArrayIndex, SelfExpr, SawType, IntLiteral, ForceUnwrap
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

    def _emit_panic(self, message: str, line: int = 0):
        """Emit a runtime panic via the saw_panic seam, then terminate the block.

        The single lowering for every compiler-emitted panic (div/mod by zero,
        integer overflow, shift range, bounds, force-unwrap of None, try! on
        Err, allocation failure): the whole message is one interned private byte
        constant handed to saw_panic(ptr, len), which is noreturn. The
        `unreachable` terminates the block. The caller must have positioned the
        builder in the panicking block. In the hosted profile saw_panic prints
        the message and aborts; in the freestanding profile the environment
        provides saw_panic.

        Design 122 unit I: every one of these carries the SAME
        `panic at FILE:LINE: ` prefix `panic()`/`assert()` already used. A trap
        that cannot say which line trapped is the weak link in a safety story
        built on trapping instead of corrupting memory. `line` is the panicking
        expression's own line when the caller has an AST node to read; otherwise
        it is the line of the statement being lowered, which is what a check
        emitted deep inside an operator helper has to fall back on.

        The location folds into the message constant rather than becoming extra
        arguments, so a panic site still costs one relocation and one call; the
        constants are interned by TEXT (via `_raw_bytes_ptr`), so repeated
        checks on one line share a single global.

        The format is the same in EVERY profile. Gating the FILE half behind
        `freestanding` was measured and rejected: it saves only
        `len(basename) - 4` bytes per site (4 bytes for a `main.saw`-sized name)
        because what actually costs size is that a per-site LINE makes each
        message unique, which the freestanding build pays either way.
        """
        message = self._panic_location_prefix(line or self._di_current_line()) + message
        if not message.endswith("\n"):
            message += "\n"
        msg_ptr, msg_len = self._raw_bytes_ptr(message)
        self.builder.call(self.functions["__saw_rt_panic"], [msg_ptr, msg_len])
        self.builder.unreachable()

    def _alloc_or_panic(self, size: int, align: int, what: str, line: int = 0):
        """Call the allocation seam, panicking if it refuses (design 123).

        The compiler's OWN allocation sites — a spawned task's control block and
        an escaping closure's heap environment — have no signature to report a
        failure through, so they sit in the infallible tier alongside
        `Box.make`. Before this the returned NULL was bitcast and stored through
        immediately: a segfault with no message, where the policy asks for a
        named panic. Returns the (non-null) block; the builder is left in the
        continuation block.

        `_emit_panic` builds its message from an interned byte constant rather
        than allocating one, so the failure path does not need the allocator
        that just refused.
        """
        word = self.int_type
        raw = self.builder.call(
            self.functions["__saw_rt_alloc"],
            [ir.Constant(word, size), ir.Constant(word, align)], name="alloc_raw")
        null = ir.Constant(ir.IntType(8).as_pointer(), None)
        func = self.builder.function
        panic_bb = func.append_basic_block("alloc_panic")
        cont_bb = func.append_basic_block("alloc_ok")
        self.builder.cbranch(self.builder.icmp_unsigned('==', raw, null),
                             panic_bb, cont_bb)
        self.builder.position_at_end(panic_bb)
        self._emit_panic(f"{what}: allocation failed", line=line)
        self.builder.position_at_end(cont_bb)
        return raw

    def _check_divisor_nonzero(self, divisor, line: int = 0):
        """Guard an integer division/modulo: panic if `divisor` is zero.

        Emits `if divisor == 0 { panic } else { continue }` and leaves the
        builder positioned in the continue block, where the raw sdiv/srem is
        then generated. Needed because arm64 does not trap on integer
        divide-by-zero, so without this the program silently returns garbage.
        (INT_MIN / -1 overflow is intentionally NOT handled here; integer
        overflow semantics are an open spec question — see todo_jul26.md #5/#7.)

        `line` is the dividing expression's own source line for the panic
        message (design 122 unit I); 0 falls back to the statement's line.
        """
        zero = ir.Constant(divisor.type, 0)
        is_zero = self.builder.icmp_signed('==', divisor, zero, name="divzero_check")
        func = self.builder.function
        panic_bb = func.append_basic_block(name="div_panic")
        cont_bb = func.append_basic_block(name="div_cont")
        self.builder.cbranch(is_zero, panic_bb, cont_bb)

        self.builder.position_at_end(panic_bb)
        self._emit_panic("division by zero", line=line)

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

    def _checked_arith(self, op: str, left, right, signed: bool, line: int = 0):
        """Emit an overflow-checked integer add/sub/mul (design 31).

        Uses the `llvm.{s,u}{add,sub,mul}.with.overflow` intrinsic and branches
        to the standard panic seam ("integer overflow") when the overflow flag is
        set, mirroring the div-by-zero panic-block pattern. Leaves the builder in
        the non-overflowing continuation block and returns the wrapped result.

        `line` is the arithmetic expression's own source line for the panic
        message (design 122 unit I); 0 falls back to the statement's line.
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
        self._emit_panic("integer overflow", line=line)

        self.builder.position_at_end(cont_bb)
        return result

    def _check_div_no_overflow(self, dividend, divisor, line: int = 0):
        """Guard a *signed* division/modulo against the `INT_MIN / -1` overflow.

        `INT_MIN / -1` is +2^(w-1), unrepresentable in a w-bit signed integer (C
        UB, and a hardware trap on some targets). Panics with "integer overflow"
        for both `/` and `%` (see design 31: `%`'s mathematically-zero result is
        defined via the same panic for consistency with division). Emitted beside
        the existing zero-divisor check; leaves the builder in the continue block.

        `line` is the dividing expression's own source line for the panic
        message (design 122 unit I); 0 falls back to the statement's line.
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
        self._emit_panic("integer overflow", line=line)

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

    def _emit_shift(self, op: str, left, right, signed: bool, line: int = 0):
        """Emit `<<` / `>>` with a runtime range check (design 50).

        A shift amount that is negative or >= the left operand's bit width panics
        with "shift out of range" (the checked-arithmetic house rule; Rust-debug
        precedent). Both cases fold into one *unsigned* `amount >= width` compare:
        a negative signed amount reinterpreted as unsigned is enormous, so it is
        caught too. The compare runs at the amount's own width *before* narrowing,
        so a large amount can't be truncated down into the legal range first.
        `>>` lowers to `ashr` (arithmetic) for a signed left operand, `lshr`
        (logical) for an unsigned one. `line` is the shifting expression's own
        source line for the panic message (design 122 unit I); 0 falls back to
        the statement's line.
        """
        width = left.type.width
        wconst = ir.Constant(right.type, width)
        oob = self.builder.icmp_unsigned('>=', right, wconst, name="shift_oob")

        func = self.builder.function
        panic_bb = func.append_basic_block(name="shift_panic")
        cont_bb = func.append_basic_block(name="shift_cont")
        self.builder.cbranch(oob, panic_bb, cont_bb)

        self.builder.position_at_end(panic_bb)
        self._emit_panic("shift out of range", line=line)

        self.builder.position_at_end(cont_bb)
        # In-range now (amount < width <= 64): safe to narrow to the shift width.
        amt = self._reconcile_int_width(self.builder, right, left.type)
        if op == '<<':
            return self.builder.shl(left, amt, name="shltmp")
        if signed:
            return self.builder.ashr(left, amt, name="ashrtmp")
        return self.builder.lshr(left, amt, name="lshrtmp")

    def _emit_array_bounds_check(self, index_val, count, index_expr):
        """Panic if a fixed-array index is out of range (design 63 T1b).

        `0 <= i < N` folded into one UNSIGNED compare `i >= N`: a negative index
        reinterpreted as unsigned is enormous, so it is caught by the same test.
        N is the compile-time array length. ALWAYS ON, every profile, no disable
        flag (the same posture as integer overflow, design 31). A CONSTANT index
        never reaches here — an out-of-range constant is already a compile error
        and an in-range one needs no guard — so this only guards genuinely
        dynamic indices, and the optimizer folds it away where it can prove the
        index in range (hot-loop tests stay clean). Raw-pointer / UnsafeMemory
        indexing is deliberately NOT routed here (the explicit unsafe escape).
        """
        if isinstance(index_expr, IntLiteral):
            return
        if not isinstance(index_val.type, ir.IntType):
            return
        nconst = ir.Constant(index_val.type, count)
        oob = self.builder.icmp_unsigned('>=', index_val, nconst, name="idx_oob")
        func = self.builder.function
        panic_bb = func.append_basic_block(name="idx_panic")
        cont_bb = func.append_basic_block(name="idx_cont")
        self.builder.cbranch(oob, panic_bb, cont_bb)
        self.builder.position_at_end(panic_bb)
        self._emit_panic("index out of range",
                         line=getattr(index_expr, 'line', 0))
        self.builder.position_at_end(cont_bb)

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

        # design 81 rider: a bare integer literal mixed with a fixed-width integer
        # operand adopts that operand's width (the typechecker already
        # range-checked it and typed the result as the fixed-width type). Without
        # this the checked-arith intrinsic sees `i32` vs the platform-width `i64`
        # literal and ICEs "arg mismatch". Both operand orders; only when both are
        # integers of different widths and the wide side is a bare literal.
        if (isinstance(left.type, ir.IntType) and isinstance(right.type, ir.IntType)
                and left.type.width != right.type.width):
            r_lit = (isinstance(expr.right, IntLiteral)
                     and getattr(expr.right, 'suffix', None) is None)
            l_lit = (isinstance(expr.left, IntLiteral)
                     and getattr(expr.left, 'suffix', None) is None)
            if r_lit:
                right = self._reconcile_int_width(self.builder, right, left.type)
            elif l_lit:
                left = self._reconcile_int_width(self.builder, left, right.type)

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
                                    self._int_is_signed(expr.left),
                                    line=getattr(expr, 'line', 0))

        if expr.op == '+':
            if isinstance(left.type, ir.PointerType):
                # Pointer arithmetic: ptr + offset
                return self.builder.gep(left, [right], name="ptr_add")
            if is_float:
                return self.builder.fadd(left, right, name="addtmp")
            # Integer add: overflow panics (design 31).
            return self._checked_arith('+', left, right, self._int_is_signed(expr.left),
                                       line=getattr(expr, 'line', 0))

        elif expr.op == '-':
            if isinstance(left.type, ir.PointerType):
                # Pointer arithmetic: ptr - offset (negate offset and add)
                neg_right = self.builder.neg(right, name="neg_offset")
                return self.builder.gep(left, [neg_right], name="ptr_sub")
            if is_float:
                return self.builder.fsub(left, right, name="subtmp")
            return self._checked_arith('-', left, right, self._int_is_signed(expr.left),
                                       line=getattr(expr, 'line', 0))

        elif expr.op == '*':
            if is_float:
                return self.builder.fmul(left, right, name="multmp")
            return self._checked_arith('*', left, right, self._int_is_signed(expr.left),
                                       line=getattr(expr, 'line', 0))

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
            self._check_divisor_nonzero(right, line=getattr(expr, 'line', 0))
            if self._int_is_signed(expr.left):
                self._check_div_no_overflow(left, right, line=getattr(expr, 'line', 0))
                return self.builder.sdiv(left, right, name="divtmp")
            return self.builder.udiv(left, right, name="udivtmp")

        elif expr.op == '%':
            # Modulo only works on integers; same zero-divisor panic as /, and
            # the same signed/unsigned split: srem (with the INT_MIN / -1 overflow
            # panic) for signed operands, urem for unsigned.
            self._check_divisor_nonzero(right, line=getattr(expr, 'line', 0))
            if self._int_is_signed(expr.left):
                self._check_div_no_overflow(left, right, line=getattr(expr, 'line', 0))
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

        elif expr.op in ('<', '>', '<=', '>='):
            # Ordering (design 48): Float keeps IEEE fcmp_ordered (every compare
            # with a NaN is false); integers use icmp. String and user Comparable
            # types desugar to `compare()` via `_emit_compare`, whose Ordering
            # result is turned back into the boolean the operator wants.
            st = self._comparison_operand_type(expr)
            if is_float:
                return self.builder.fcmp_ordered(expr.op, left, right, name="fcmptmp")
            # String / struct / (payload-free or payload) enum: order via
            # `compare()`. Everything else (integers, raw pointers) uses icmp.
            if st is not None and st.kind in (TypeKind.STRING, TypeKind.STRUCT,
                                              TypeKind.ENUM):
                return self._ordering_to_bool(expr.op,
                                              self._emit_compare(left, right, st))
            # Unsigned integer operands must compare with icmp_unsigned: under a
            # signed compare a UInt with the high bit set reads as negative, so
            # `UInt64.max > 1` would be false (design 41 / mirror of the udiv
            # split above). Only genuine unsigned kinds switch; Int and raw
            # pointers stay signed as before.
            icmp = (self.builder.icmp_signed if self._int_is_signed(expr.left)
                    else self.builder.icmp_unsigned)
            return icmp(expr.op, left, right, name="icmptmp")

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

    # =========================================================================
    # Ordering lowering (design 48)
    #
    # `_emit_compare` is the recursive dual of `_emit_equals`: it lowers
    # `a.compare(b)` for any Comparable type to an i32 that equals the tag of the
    # resulting `Ordering` value (payload-free enums, incl. Ordering itself, are
    # a bare i32 tag). Integers/Float compare three-way directly; String calls
    # its byte-lexicographic `compare`; a struct dispatches to its (synthesized
    # or custom) compare, or compares fields lexicographically inline; an enum
    # orders by variant tag then active-payload lexicographic. `< <= > >=` turn
    # that Ordering back into a boolean via `_ordering_to_bool`.
    # =========================================================================

    def _comparison_operand_type(self, expr: BinaryOp):
        """The Saw type a `< <= > >=` operand was checked at (same extraction as
        the equality path), substituted for the active monomorphization."""
        return self._equality_operand_type(expr)

    def _ordering_tags(self):
        """(less, equal, greater) tag ints for the builtin Ordering enum. Falls
        back to the declared order 0/1/2 if the enum is not registered."""
        info = self.enum_types.get("Ordering")
        if info is not None:
            tags = info[1]
            return (tags.get("Less", 0), tags.get("Equal", 1), tags.get("Greater", 2))
        return (0, 1, 2)

    def _ordering_to_bool(self, op, cmp_i32):
        """Turn an Ordering tag (i32) into the boolean the operator wants:
        `<` is Less, `>` is Greater, `<=` is not-Greater, `>=` is not-Less."""
        less, equal, greater = self._ordering_tags()
        i32 = ir.IntType(32)
        if op == '<':
            return self.builder.icmp_signed('==', cmp_i32, ir.Constant(i32, less), name="lt")
        if op == '>':
            return self.builder.icmp_signed('==', cmp_i32, ir.Constant(i32, greater), name="gt")
        if op == '<=':
            return self.builder.icmp_signed('!=', cmp_i32, ir.Constant(i32, greater), name="le")
        if op == '>=':
            return self.builder.icmp_signed('!=', cmp_i32, ir.Constant(i32, less), name="ge")
        raise ValueError(f"not an ordering operator: {op}")

    def _emit_int_compare(self, left, right):
        """Three-way integer compare -> Ordering tag (i32). Signed, matching the
        rest of the comparison codegen."""
        less, equal, greater = self._ordering_tags()
        i32 = ir.IntType(32)
        lt = self.builder.icmp_signed('<', left, right, name="cmp_lt")
        gt = self.builder.icmp_signed('>', left, right, name="cmp_gt")
        acc = self.builder.select(gt, ir.Constant(i32, greater),
                                  ir.Constant(i32, equal), name="cmp_ge")
        return self.builder.select(lt, ir.Constant(i32, less), acc, name="cmp3")

    def _emit_float_compare(self, left, right):
        """Three-way Float compare -> Ordering tag (i32), IEEE-ordered. A NaN is
        unordered, so `<` and `>` are both false and it lands on Equal (there is
        no total order over NaN; documented). +0.0 and -0.0 compare Equal."""
        less, equal, greater = self._ordering_tags()
        i32 = ir.IntType(32)
        lt = self.builder.fcmp_ordered('<', left, right, name="fcmp_lt")
        gt = self.builder.fcmp_ordered('>', left, right, name="fcmp_gt")
        acc = self.builder.select(gt, ir.Constant(i32, greater),
                                  ir.Constant(i32, equal), name="fcmp_ge")
        return self.builder.select(lt, ir.Constant(i32, less), acc, name="fcmp3")

    def _emit_compare(self, left, right, saw_type):
        """Emit an i32 Ordering tag for `left.compare(right)`, recursively."""
        if isinstance(left.type, ir.DoubleType):
            return self._emit_float_compare(left, right)
        st = self._resolve_type_alias(saw_type) if saw_type is not None else None
        if st is not None:
            k = st.kind
            if k == TypeKind.STRING:
                return self._emit_string_compare(left, right)
            if k == TypeKind.STRUCT and not isinstance(left.type, ir.IntType):
                return self._emit_struct_compare(left, right, st)
            if k == TypeKind.ENUM:
                return self._emit_enum_compare(left, right, st)
        # Integers (incl. payload-free enum tags reaching here as a fallback).
        return self._emit_int_compare(left, right)

    def _emit_string_compare(self, left, right):
        """String ordering is byte-lexicographic via the stdlib `String.compare`."""
        fn = self.functions.get(self._mangle_method_name("String", "compare"))
        if fn is None:
            # String.compare not linked: fall back to Equal so codegen stays total.
            _, equal, _ = self._ordering_tags()
            return ir.Constant(ir.IntType(32), equal)
        return self.builder.call(fn, [left, right], name="strcmp")

    def _emit_struct_compare(self, left, right, saw_type):
        """Struct ordering: dispatch to the type's `compare` (synthesized or
        custom) if one exists, else compare fields lexicographically inline."""
        base = self._type_method_base(saw_type)
        mangled = self._mangle_method_name(base, "compare") if base else None
        if mangled is not None and mangled in self.functions:
            return self.builder.call(self.functions[mangled], [left, right],
                                     name="cmp_call")
        return self._emit_memberwise_compare(left, right, saw_type)

    def _emit_memberwise_compare(self, left, right, saw_type):
        """Lexicographic field-by-field compare over a struct value -> Ordering
        tag. The first field whose compare is not Equal decides; if all fields
        are Equal the struct is Equal. Field compares are pure, so the fold uses
        selects (no short-circuit needed for correctness)."""
        key = self._type_method_base(saw_type)
        llvm_struct_type, field_order = self.struct_types[key]
        base_fields = self.namespace.get_struct_fields(saw_type.struct_name) or {}
        subst = {}
        struct_sym = self.namespace._lookup_struct_deep(saw_type.struct_name)
        if struct_sym and saw_type.type_args:
            for tp, arg in zip(struct_sym.type_params, saw_type.type_args):
                subst[tp.name] = arg
        fcs = []
        for i, fname in enumerate(field_order):
            ftype = base_fields.get(fname)
            if ftype is not None and subst:
                ftype = ftype.substitute(subst)
            lf = self.builder.extract_value(left, i, name=f"l_{fname}")
            rf = self.builder.extract_value(right, i, name=f"r_{fname}")
            fcs.append(self._emit_compare(lf, rf, ftype))
        less, equal, greater = self._ordering_tags()
        i32 = ir.IntType(32)
        acc = ir.Constant(i32, equal)
        for fc in reversed(fcs):
            is_eq = self.builder.icmp_signed('==', fc, ir.Constant(i32, equal),
                                             name="fld_eq")
            acc = self.builder.select(is_eq, acc, fc, name="lex_sel")
        return acc

    def _emit_enum_compare(self, left, right, saw_type):
        """Enum ordering (design 48): order by variant tag (declaration order),
        then, for equal tags, lexicographically over the active variant's payload
        fields. Payload-free enums are a bare i32 tag, so tag order is the whole
        answer."""
        mangled = mangle_named(saw_type.enum_name, saw_type.type_args)
        info = self.enum_types.get(mangled) or self.enum_types.get(saw_type.enum_name)
        llvm_enum_type, variant_tags, variant_info = info
        i32 = ir.IntType(32)
        less, equal, greater = self._ordering_tags()

        # Payload-free enum: the value IS the tag; compare tags three-way.
        if not isinstance(llvm_enum_type, ir.LiteralStructType):
            return self._emit_int_compare(left, right)

        left_tag = self.builder.extract_value(left, 0, name="l_tag")
        right_tag = self.builder.extract_value(right, 0, name="r_tag")
        tag_cmp = self._emit_int_compare(left_tag, right_tag)
        tags_eq = self.builder.icmp_signed('==', left_tag, right_tag, name="tags_eq")

        func = self.builder.function
        entry_bb = self.builder.block
        payload_bb = func.append_basic_block("cmp_payload")
        merge_bb = func.append_basic_block("cmp_merge")
        # Tags differ -> the tag order is the answer; equal -> compare payloads.
        self.builder.cbranch(tags_eq, payload_bb, merge_bb)

        self.builder.position_at_end(payload_bb)
        equal_bb = func.append_basic_block("cmp_payload_free")
        switch = self.builder.switch(left_tag, equal_bb)
        payload_array_type = llvm_enum_type.elements[1]
        incoming = []
        for variant_name, fields in variant_info.items():
            if not fields:
                continue  # payload-free variant -> Equal (default block)
            arm_bb = func.append_basic_block(f"cmp_{variant_name}")
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
            fcs = []
            for idx, (fname, ftype) in enumerate(fields):
                l_fp = self.builder.gep(l_sp, [ir.Constant(i32, 0),
                                               ir.Constant(i32, idx)], inbounds=True)
                r_fp = self.builder.gep(r_sp, [ir.Constant(i32, 0),
                                               ir.Constant(i32, idx)], inbounds=True)
                lf = self.builder.load(l_fp, name=f"l_{fname}")
                rf = self.builder.load(r_fp, name=f"r_{fname}")
                fcs.append(self._emit_compare(lf, rf, ftype))
            arm_result = ir.Constant(i32, equal)
            for fc in reversed(fcs):
                is_eq = self.builder.icmp_signed('==', fc, ir.Constant(i32, equal),
                                                 name="fld_eq")
                arm_result = self.builder.select(is_eq, arm_result, fc, name="lex_sel")
            arm_end = self.builder.block
            self.builder.branch(merge_bb)
            incoming.append((arm_result, arm_end))

        self.builder.position_at_end(equal_bb)
        self.builder.branch(merge_bb)

        self.builder.position_at_end(merge_bb)
        phi = self.builder.phi(i32, name="enum_cmp")
        phi.add_incoming(tag_cmp, entry_bb)                 # tags differ
        phi.add_incoming(ir.Constant(i32, equal), equal_bb)  # payload-free, equal tag
        for val, blk in incoming:
            phi.add_incoming(val, blk)
        return phi

    # =========================================================================
    # Hash lowering (design 48)
    #
    # `_emit_hash` streams a value into a Hasher (a `{ i64 state }` struct at
    # `hasher_ptr`) with the FNV-1a step, recursing structurally. It streams
    # exactly the fields `==` compares, so the hash/== contract holds for auto
    # and synthesized conformers. Primitives mix directly; String dispatches to
    # its byte-streaming `String.hash`; a struct dispatches to its (synthesized
    # or custom) hash, or streams fields inline; an enum streams the tag then the
    # active variant's payload.
    # =========================================================================

    _FNV_PRIME = 1099511628211

    def _fnv_write_int(self, hasher_ptr, x_i64):
        """One FNV-1a step: state = (state ^ x) * prime, in place at hasher_ptr.
        LLVM `mul` wraps (no nsw/nuw), which is exactly the FNV wrap."""
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        state_ptr = self.builder.gep(hasher_ptr, [ir.Constant(i32, 0),
                                                  ir.Constant(i32, 0)],
                                     inbounds=True, name="hstate_ptr")
        state = self.builder.load(state_ptr, name="hstate")
        xored = self.builder.xor(state, x_i64, name="hxor")
        mixed = self.builder.mul(xored, ir.Constant(i64, self._FNV_PRIME), name="hmix")
        self.builder.store(mixed, state_ptr)

    def _emit_hash(self, value, saw_type, hasher_ptr):
        """Stream `value` into the Hasher at `hasher_ptr` (design 48)."""
        lt = value.type
        i64 = ir.IntType(64)
        st = self._resolve_type_alias(saw_type) if saw_type is not None else None

        if isinstance(lt, ir.DoubleType):
            # Normalize -0.0 to +0.0 so equal floats hash identically (they
            # compare Equal). NaN bit patterns are not normalized (NaN != NaN, so
            # the contract imposes nothing); documented.
            zero = ir.Constant(ir.DoubleType(), 0.0)
            is_zero = self.builder.fcmp_ordered('==', value, zero, name="hf_zero")
            bits = self.builder.bitcast(value, i64, name="hf_bits")
            norm = self.builder.select(is_zero, ir.Constant(i64, 0), bits, name="hf_norm")
            self._fnv_write_int(hasher_ptr, norm)
            return

        if st is not None:
            k = st.kind
            if k == TypeKind.STRING:
                self._emit_string_hash(value, hasher_ptr)
                return
            if k == TypeKind.TUPLE:
                for i, et in enumerate(st.element_types or []):
                    ev = self.builder.extract_value(value, i, name=f"h_e{i}")
                    self._emit_hash(ev, et, hasher_ptr)
                return
            if k == TypeKind.OPTIONAL:
                self._emit_optional_hash(value, st, hasher_ptr)
                return
            if k == TypeKind.ARRAY:
                for i in range(st.array_size or 0):
                    ev = self.builder.extract_value(value, i, name=f"h_a{i}")
                    self._emit_hash(ev, st.array_element_type, hasher_ptr)
                return
            if k == TypeKind.STRUCT and not isinstance(lt, ir.IntType):
                self._emit_struct_hash(value, st, hasher_ptr)
                return
            if k == TypeKind.ENUM and isinstance(lt, ir.LiteralStructType):
                self._emit_enum_hash(value, st, hasher_ptr)
                return

        # Integers, Bool, payload-free enum tags: widen/narrow to i64 and mix.
        if isinstance(lt, ir.IntType):
            if lt.width < 64:
                x = self.builder.zext(value, i64, name="h_zext")
            elif lt.width > 64:
                x = self.builder.trunc(value, i64, name="h_trunc")
            else:
                x = value
            self._fnv_write_int(hasher_ptr, x)
            return

        raise ValueError(f"cannot lower hash for LLVM type {lt}")

    def _emit_string_hash(self, value, hasher_ptr):
        """String hashing streams the bytes via the stdlib `String.hash`."""
        fn = self.functions.get(self._mangle_method_name("String", "hash"))
        if fn is not None:
            self.builder.call(fn, [value, hasher_ptr])

    def _emit_struct_hash(self, value, saw_type, hasher_ptr):
        """Struct hashing: dispatch to the type's `hash` (synthesized or custom)
        if one exists, else stream fields inline (auto-conform POD)."""
        base = self._type_method_base(saw_type)
        mangled = self._mangle_method_name(base, "hash") if base else None
        if mangled is not None and mangled in self.functions:
            self.builder.call(self.functions[mangled], [value, hasher_ptr])
            return
        self._emit_memberwise_hash(value, saw_type, hasher_ptr)

    def _emit_memberwise_hash(self, value, saw_type, hasher_ptr):
        """Stream each field of a struct value into the Hasher in field order."""
        key = self._type_method_base(saw_type)
        llvm_struct_type, field_order = self.struct_types[key]
        base_fields = self.namespace.get_struct_fields(saw_type.struct_name) or {}
        subst = {}
        struct_sym = self.namespace._lookup_struct_deep(saw_type.struct_name)
        if struct_sym and saw_type.type_args:
            for tp, arg in zip(struct_sym.type_params, saw_type.type_args):
                subst[tp.name] = arg
        for i, fname in enumerate(field_order):
            ftype = base_fields.get(fname)
            if ftype is not None and subst:
                ftype = ftype.substitute(subst)
            fv = self.builder.extract_value(value, i, name=f"h_{fname}")
            self._emit_hash(fv, ftype, hasher_ptr)

    def _emit_optional_hash(self, value, saw_type, hasher_ptr):
        """Optional hashing: stream the is-some flag, then the payload only when
        Some (a None slot's payload is undefined, so it is never read)."""
        i64 = ir.IntType(64)
        is_some = self.builder.extract_value(value, 0, name="h_some")
        self._fnv_write_int(hasher_ptr, self.builder.zext(is_some, i64, name="h_some64"))
        func = self.builder.function
        some_bb = func.append_basic_block("h_opt_some")
        merge_bb = func.append_basic_block("h_opt_merge")
        self.builder.cbranch(is_some, some_bb, merge_bb)
        self.builder.position_at_end(some_bb)
        payload = self.builder.extract_value(value, 1, name="h_opt_val")
        self._emit_hash(payload, saw_type.inner_type, hasher_ptr)
        self.builder.branch(merge_bb)
        self.builder.position_at_end(merge_bb)

    def _emit_enum_hash(self, value, saw_type, hasher_ptr):
        """Payload-carrying enum hashing: stream the tag, then the active
        variant's payload fields. (Payload-free enums are a bare i32 and hash via
        the integer path in `_emit_hash`.)"""
        mangled = mangle_named(saw_type.enum_name, saw_type.type_args)
        info = self.enum_types.get(mangled) or self.enum_types.get(saw_type.enum_name)
        llvm_enum_type, variant_tags, variant_info = info
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        tag = self.builder.extract_value(value, 0, name="h_tag")
        self._fnv_write_int(hasher_ptr, self.builder.zext(tag, i64, name="h_tag64"))

        func = self.builder.function
        merge_bb = func.append_basic_block("h_enum_merge")
        switch = self.builder.switch(tag, merge_bb)
        payload_array_type = llvm_enum_type.elements[1]
        for variant_name, fields in variant_info.items():
            if not fields:
                continue  # payload-free variant -> nothing beyond the tag
            arm_bb = func.append_basic_block(f"h_{variant_name}")
            switch.add_case(ir.Constant(i32, variant_tags[variant_name]), arm_bb)
            self.builder.position_at_end(arm_bb)
            payload = self.builder.extract_value(value, 1, name="h_pl")
            param_struct_type = ir.LiteralStructType(
                [self._get_llvm_type(t) for _, t in fields])
            alloca = self._entry_alloca(payload_array_type, name="h_pl_slot")
            self.builder.store(payload, alloca)
            sp = self.builder.bitcast(alloca, ir.PointerType(param_struct_type),
                                      name="h_sp")
            for idx, (fname, ftype) in enumerate(fields):
                fp = self.builder.gep(sp, [ir.Constant(i32, 0),
                                           ir.Constant(i32, idx)], inbounds=True)
                fv = self.builder.load(fp, name=f"h_{fname}")
                self._emit_hash(fv, ftype, hasher_ptr)
            self.builder.branch(merge_bb)
        self.builder.position_at_end(merge_bb)

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
            # Negating an integer LITERAL folds to the negated constant at the
            # operand's width (design 77 item 8): this makes `-128i8` the value
            # Int8.min directly rather than a runtime negation of the i8 bit
            # pattern `128` (= -128), which would overflow and panic. The
            # typechecker range-checked the negated value against the target.
            if isinstance(expr.operand, IntLiteral) and isinstance(operand.type, ir.IntType):
                return ir.Constant(operand.type, -expr.operand.value)
            # Integer negation is `0 - x`; negating the signed minimum overflows
            # (its magnitude is unrepresentable) and panics (design 31). Unary `-`
            # is signed-only (typechecker allows signed Int/fixed-width/Float), so
            # a signed checked subtract is exactly right.
            zero = ir.Constant(operand.type, 0)
            return self._checked_arith('-', zero, operand, True,
                                       line=getattr(expr, 'line', 0))

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

        # design 131: `move o!` yields the PAYLOAD of the moved optional. The
        # binding is retired exactly as `move o` retires it (flag cleared below,
        # no writeback), so this is a pure projection of the already-loaded
        # value — plus the force-unwrap's None panic.
        if expr.unwrap:
            is_some = self.builder.extract_value(value, 0, name="move_is_some")
            func = self.builder.function
            ok_bb = func.append_basic_block(name="move_unwrap.ok")
            panic_bb = func.append_basic_block(name="move_unwrap.panic")
            self.builder.cbranch(is_some, ok_bb, panic_bb)
            self.builder.position_at_end(panic_bb)
            self._emit_panic("force unwrap of None", line=expr.line)
            self.builder.position_at_end(ok_bb)
            value = self.builder.extract_value(value, 1, name="move_unwrapped")

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
                gv = self._static_global(inner_expr)
                if gv is not None:
                    return gv
                raise ValueError(f"Undefined variable: {var_name}")
            # Re-borrowing an existing reference binding (`&var ref` / `&ref`,
            # design 56): the alloca holds the reference (a pointer to the real
            # value), so forward THAT pointer — not `&alloca` (one level too
            # many). A non-reference binding yields its alloca as before.
            var_type = self.variable_types.get(var_name)
            if var_type is not None and var_type.kind == TypeKind.REFERENCE:
                return self.builder.load(self.variables[var_name],
                                         name=f"{var_name}_reborrow")
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
        elif isinstance(inner_expr, ForceUnwrap):
            # `&(opt!)` — a pointer into the optional's payload slot (guarded by a
            # None-check, matching force-unwrap read semantics). Optionals lower to
            # `{ i1 is_some, T payload }`; address the underlying optional lvalue and
            # GEP to field 1. Used to address an opt-encoded coroutine-frame method
            # receiver (design 84) and any `&` into an optional's contents.
            opt_ptr = self._generate_reference_expr(
                ReferenceExpr(expr=inner_expr.expr, mutable=expr.mutable))
            is_some = self.builder.load(
                self.builder.gep(opt_ptr,
                                 [ir.Constant(ir.IntType(32), 0),
                                  ir.Constant(ir.IntType(32), 0)], name="is_some_ptr"),
                name="is_some")
            func = self.builder.function
            ok_bb = func.append_basic_block(name="unwrap_ref.ok")
            panic_bb = func.append_basic_block(name="unwrap_ref.panic")
            self.builder.cbranch(is_some, ok_bb, panic_bb)
            self.builder.position_at_end(panic_bb)
            self._emit_panic("force unwrap of None",
                             line=getattr(inner_expr, 'line', 0))
            self.builder.position_at_end(ok_bb)
            return self.builder.gep(opt_ptr,
                                    [ir.Constant(ir.IntType(32), 0),
                                     ir.Constant(ir.IntType(32), 1)],
                                    name="unwrap_payload_ptr")
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
            # Dynamic bounds check (design 63 T1b) on `&arr[i]`.
            self._emit_array_bounds_check(index_val, pointee.count, expr.index)
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
        # Distinct-type projection (design 63): if the operand is a distinct
        # `type` alias, resolve it to its underlying so the signedness/size
        # logic below reads the real numeric kind rather than STRUCT.
        if from_saw_type is not None:
            _seen = set()
            while (from_saw_type is not None and from_saw_type.kind == TypeKind.STRUCT
                   and from_saw_type.struct_name
                   and self.namespace.lookup_type_alias(from_saw_type.struct_name)
                   and from_saw_type.struct_name not in _seen):
                _seen.add(from_saw_type.struct_name)
                from_saw_type = self._resolve_type_alias(from_saw_type)
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

        # Identity projection (design 63): a distinct alias over a non-integer
        # underlying (String / struct) has the same layout as that underlying,
        # so `n as String` / `p as Point` is a representation no-op.
        if value.type == to_llvm:
            return value

        raise ValueError(f"Cannot cast from {value.type} to {to_llvm}")

"""
Function and method call generation for the Saw code generator.

This module provides mixin methods for generating LLVM IR code for function
calls, method calls, static method calls, and built-in functions like print
and sizeof.

Usage:
    class CodeGenerator(CallsMixin, ...):
        pass
"""

from dataclasses import dataclass
from typing import Any, List
from llvmlite import ir
from ast_nodes import (
    Expression, FunctionCall, StructInit, Argument, SawType, TypeKind,
    MethodCall, MemberAccess, Identifier, SelfExpr, EnumInit, ArrayIndex,
    ForceUnwrap, ReferenceExpr, StringLiteral, StringInterpolation, TupleIndex,
    NoneLiteral
)
from .mangle import content_tag, mangle_type
from .operators import _UNSIGNED_INT_KINDS


@dataclass
class PreparedValue(Expression):
    """A synthesized expression node carrying an already-generated LLVM value.

    Design 137. Codegen builds a `MethodCall` for `format(into:)` whose argument
    is a `StringBuilder` it just allocated on the stack. Wrapping that value in
    an expression node lets the call go through the ORDINARY method dispatch —
    vtable slot for an erased `&any Printable` receiver included — rather than a
    second, divergent copy of it.

    It is a REAL `Expression` (design 194 unit 5): it used to be a bare class
    carrying four hand-set attributes, which meant every transfer-path read of a
    base annotation — `needs_copy`, `closure_lend`, `place_value_read` — had to
    be a `getattr` with a default, in case the thing it was handed was this. It
    travels in argument position, so it owes the whole `Expression` contract or
    the readers cannot be direct.
    """
    value: Any = None


class _StampedSymbol:
    """Carries a stamped overload symbol into `_compose_overload_suffix`.

    That helper reads `mangled_symbol` off a declaration node; at a CALL site the
    same string arrives on the expression as `resolved_symbol`. Wrapping it keeps
    one implementation of the compose rule rather than two spellings of it.
    """

    def __init__(self, mangled_symbol):
        self.mangled_symbol = mangled_symbol


class CallsMixin:
    """Mixin providing function and method call generation methods for CodeGenerator.

    Methods:
        _generate_function_call: Generate code for function calls
        _generate_print: Generate code for the print built-in
        _generate_sizeof: Generate code for the sizeof built-in
        _generate_method_call: Generate code for method calls
        _generate_static_method_call: Generate code for static method calls
        _resolve_module_chain: Resolve module access chains
        _generate_module_function_call: Generate module function calls
        _generate_module_struct_init: Generate module struct initialization
        _get_member_pointer: Get pointer to struct field for mutable access
        _generate_self_expr: Generate code for 'self' keyword
        _generate_enum_init: Generate code for enum variant initialization
    """

    # design 118 stage 3: the reactor-instance injection is retired — the executor
    # threads the instance explicitly through `SystemReactor` (std/taskgroup.saw),
    # consuming the reactor through the `Reactor` trait. (design 117's
    # `_REACTOR_INSTANCE_SEAMS` / `_reactor_instance` / the synthesized
    # `__saw_reactor()` getter are all gone.)

    def _fill_func_defaults(self, args, key):
        """Design 53: append default-value arguments for a free-function call
        that omitted trailing arguments. The default expressions are evaluated
        fresh at the call site, per call (like the method/init default path)."""
        defaults = self.func_defaults.get(key)
        if not defaults:
            return
        ptypes = self._callee_param_types(key)
        for i in range(len(args), len(defaults)):
            if defaults[i] is not None:
                args.append(self._gen_default_value(
                    defaults[i], ptypes[i] if i < len(ptypes) else None))

    def _callee_param_types(self, key):
        """The declared LLVM parameter types of an already-declared callee."""
        llvm_func = self.functions.get(key)
        if llvm_func is None:
            return []
        return list(llvm_func.function_type.args)

    def _gen_default_value(self, expr, llvm_param_type):
        """One default argument, with the callee's parameter type in hand.

        A `None` default whose type mentions a type PARAMETER (`b: T = None`,
        `b: T? = None` — design 108) cannot be generated from the caller's
        context: the default expression lives on the DECLARATION, `T` is not
        bound here, and the payload type is the instantiation's to decide. Two
        different failures came out of that — no payload type at all, and an
        abstract `T` reaching the LLVM lowering.

        The callee's own parameter type answers both, and it is the authority
        anyway: an absent optional has no payload bits to compute, so the
        constant is fully determined by the slot it fills. Stamping the shared
        declaration node instead would be wrong — two calls may instantiate the
        parameter differently and the last stamp would win for both (DF-146l
        site 4).

        Every other default is generated exactly as before.
        """
        if isinstance(expr, NoneLiteral) and llvm_param_type is not None:
            none_val = self._none_constant(llvm_param_type)
            if none_val is not None:
                return none_val
        return self._gen_transfer_value(expr)

    def _none_constant(self, llvm_type):
        """An absent optional of `llvm_type`, or None if that is not one."""
        if not self._is_optional_type(llvm_type):
            return None
        value = ir.Constant(llvm_type, ir.Undefined)
        return self.builder.insert_value(value, ir.Constant(ir.IntType(1), 0), 0)

    def _planned_arg_values(self, expr, logical_defaults, gen_default=None):
        """Design 66: build the ordered argument values (excluding self) for a
        LABELED call from `expr.arg_plan`. Each plan slot is either a source-arg
        index (emit that argument's value) or None (a default-filled parameter,
        lowered from `logical_defaults[p]`). `logical_defaults` is indexed by
        logical parameter position (self already stripped). The binding rule
        never reorders bound arguments, so evaluation stays left-to-right;
        skipped defaults are interleaved into their parameter slots."""
        if gen_default is None:
            gen_default = self._gen_transfer_value
        plan = expr.arg_plan
        vals = []
        for p, ai in enumerate(plan):
            if ai is not None:
                vals.append(self._gen_transfer_value(expr.arguments[ai].value))
            else:
                vals.append(gen_default(logical_defaults[p]))
        return vals

    def _widen_int_value(self, value, to_llvm, from_type):
        """Extend an integer value to a WIDER slot (design 195, closing DF-195a).

        The rule, and it has one right answer: an implicit widening extends by the
        SOURCE's signedness. That is what preserves the two's-complement VALUE —
        a `UInt32` holding 4000000000 is 4000000000 in an `Int`, and
        sign-extending it makes -294967296. LANGUAGE_SPEC's conversion cost table
        has said "unsigned -> strictly wider signed | one `zext`" since design
        170; the widening sites picked the extension off the TARGET (or off
        nothing at all) and every unsigned source came back negative.

        `from_type` is the source's Saw type. Absent (a synthesized value, a node
        the pass has no expression for), the extension falls back to SIGNED, which
        is `_int_is_signed`'s own convention for an unannotated operand.

        POSITIONS an implicit widening happens, and where each gets its extension:

        - a value `if` / `match` arm, and the `??` DEFAULT — through a synthesized
          `as`, so design 170's own cast lowering (`_convert_int_width`) answers
        - the `??` PAYLOAD — `_generate_nil_coalesce`, which passes the payload type
        - a `let` with a wider annotation — `_generate_let_statement`
        - a `return` — `_coerce_ret_value`, which passes the returned expression
        - a struct FIELD initializer — `_coerce_field_int`, which has the field's
          own value expression
        - a call ARGUMENT and a fixed-array ELEMENT store — `_coerce_call_args` and
          the element-assignment path, which hold LLVM values with no source
          expression threaded to them and so still fall back to signed (DF-195e)
        """
        if value.type.width >= to_llvm.width:
            return value
        unsigned = False
        if from_type is not None:
            resolved = self._resolve_type_alias(from_type)
            if self.type_param_context:
                resolved = resolved.substitute(self.type_param_context)
            unsigned = resolved.kind in _UNSIGNED_INT_KINDS
        if unsigned:
            return self.builder.zext(value, to_llvm, name="widen_zext")
        return self.builder.sext(value, to_llvm, name="widen_sext")

    def _coerce_int_llvm(self, value, target, from_type=None):
        """Coerce an integer `value` to the LLVM `target` IntType (design 65
        followup). A bare integer literal reaches a fixed-width slot as the
        platform word (i64); retype the constant to the target width (out-of-range
        constants are already rejected by the typechecker). A runtime integer is
        truncated, or WIDENED through `_widen_int_value` — pass `from_type` where
        the caller has the source's Saw type, or the extension falls back to
        signed (design 195 / DF-195a)."""
        if isinstance(value, ir.Constant):
            return ir.Constant(target, value.constant)
        if value.type.width > target.width:
            return self.builder.trunc(value, target, name="arg_trunc")
        return self._widen_int_value(value, target, from_type)

    def _coerce_call_args(self, callee, args):
        """Coerce integer call arguments to the callee's exact parameter widths
        (design 65 followup) — without it a bare int literal passed to a
        fixed-width param (`f(5)` with `f(x: Int8)`) ICE'd on the call verifier
        (`i8 != i64`). Non-integer / same-width args pass through unchanged."""
        ftype = getattr(callee, 'function_type', None)
        if ftype is None:
            pointee = getattr(getattr(callee, 'type', None), 'pointee', None)
            ftype = pointee if isinstance(pointee, ir.FunctionType) else None
        if ftype is None:
            return args
        params = ftype.args
        out = []
        for i, a in enumerate(args):
            if (i < len(params) and isinstance(a.type, ir.IntType)
                    and isinstance(params[i], ir.IntType)
                    and a.type.width != params[i].width):
                a = self._coerce_int_llvm(a, params[i])
            out.append(a)
        return out

    def _coerce_ret_value(self, value, value_expr=None):
        """Coerce an integer return value to the current function's declared
        return width (design 65 followup) — a bare literal tail/`return` in a
        fixed-width-returning function (`func g() -> Int8 { 5 }`) reaches here as
        the platform word (i64) and would fail LLVM verification.

        `value_expr` is the returned EXPRESSION, whose Saw type decides a
        widening's extension (design 195 / DF-195a: `return u` for a `UInt32 u`
        from an `-> Int` function used to sign-extend and answer negative)."""
        if value is None:
            return value
        rt = self.builder.function.function_type.return_type
        if (isinstance(value.type, ir.IntType) and isinstance(rt, ir.IntType)
                and value.type.width != rt.width):
            from_type = (getattr(value_expr, 'resolved_type', None)
                         if value_expr is not None else None)
            return self._coerce_int_llvm(value, rt, from_type)
        return value

    # ---------------------------------------------------------------- design 183
    # Blocking-extern offload marshalling.
    #
    # The runtime hands a worker thread ONE machine word and calls a `word(word)`
    # thunk with it (rt/ABI.md). Design 103 v1 made that word the extern's single
    # `Int` argument, which is why the extern had to BE `(Int) -> Int`. Now the
    # word is a pointer to a slot array and the thunk is COMPILER-SYNTHESIZED per
    # extern: it reads the slots back at their declared types and makes the real
    # call, so the C ABI is the compiler's ordinary extern-call lowering rather
    # than a cast-a-function-pointer trick in the runtime's C shim. Any signature
    # the C-ABI whitelist admits works, arity included.
    #
    # A slot is one i64. Widening and reading are exact inverses, so the value
    # the extern receives is bit-for-bit the one the call site computed.
    # ---------------------------------------------------------------- #
    _BLK_SLOT = ir.IntType(64)

    def _blk_slot_write(self, value):
        """Widen one C-ABI value into its i64 slot."""
        slot = self._BLK_SLOT
        t = value.type
        if isinstance(t, ir.IntType):
            if t.width == slot.width:
                return value
            return self.builder.zext(value, slot, name="blkarg")
        if isinstance(t, ir.PointerType):
            return self.builder.ptrtoint(value, slot, name="blkarg")
        if isinstance(t, ir.DoubleType):
            return self.builder.bitcast(value, slot, name="blkarg")
        if isinstance(t, ir.FloatType):
            bits = self.builder.bitcast(value, ir.IntType(32), name="blkargf")
            return self.builder.zext(bits, slot, name="blkarg")
        # design 192 unit 2: ValueError is codegen's one internal-failure
        # convention, so sawc.py's catch-all reports every site the same way.
        raise ValueError(
            f"offload argument of LLVM type {t} is not C-ABI marshallable")

    def _blk_slot_read(self, word, target):
        """Narrow an i64 slot back to `target` — the inverse of the write."""
        if isinstance(target, ir.IntType):
            if target.width == self._BLK_SLOT.width:
                return word
            return self.builder.trunc(word, target, name="blkval")
        if isinstance(target, ir.PointerType):
            return self.builder.inttoptr(word, target, name="blkval")
        if isinstance(target, ir.DoubleType):
            return self.builder.bitcast(word, target, name="blkval")
        if isinstance(target, ir.FloatType):
            bits = self.builder.trunc(word, ir.IntType(32), name="blkvalb")
            return self.builder.bitcast(bits, target, name="blkval")
        # design 192 unit 2: see `_blk_slot_write` — one raise convention.
        raise ValueError(
            f"offload value of LLVM type {target} is not C-ABI marshallable")

    def _blk_thunk(self, name):
        """The worker-thread entry for blocking extern `name`, emitted once.

        `i64 thunk(i64 slots)`: read each argument out of the slot array at its
        declared type, call the extern, widen the result back into one word (0
        for a Void/Never extern, whose caller takes nothing).
        """
        thunks = getattr(self, '_blk_thunks', None)
        if thunks is None:
            thunks = self._blk_thunks = {}
        if name in thunks:
            return thunks[name]

        callee = self.functions[name]
        slot = self._BLK_SLOT
        i32 = ir.IntType(32)
        fn = ir.Function(self.module, ir.FunctionType(slot, [slot]),
                         name=f"__saw_blk_thunk${name}")
        fn.linkage = "internal"
        thunks[name] = fn

        saved_builder = getattr(self, 'builder', None)
        self.builder = ir.IRBuilder(fn.append_basic_block("entry"))
        try:
            base = self.builder.inttoptr(fn.args[0], slot.as_pointer(),
                                         name="blkslots")
            args = []
            for i, pt in enumerate(callee.function_type.args):
                p = self.builder.gep(base, [ir.Constant(i32, i)], name="blkslot")
                args.append(self._blk_slot_read(
                    self.builder.load(p, name="blkword"), pt))
            ret = callee.function_type.return_type
            if isinstance(ret, ir.VoidType):
                self.builder.call(callee, args)
                self.builder.ret(ir.Constant(slot, 0))
            else:
                self.builder.ret(self._blk_slot_write(
                    self.builder.call(callee, args, name="blkcall")))
        finally:
            self.builder = saved_builder
        return fn

    def _gen_offload_start(self, inner: FunctionCall):
        """`__saw_blk_start(slow(a, b))` — marshal the arguments and start the job.

        The slot array is an ENTRY-BLOCK alloca: `start` copies it into the job
        before spawning, so it need only outlive this call, and an offload inside
        a driven loop must not grow the resume frame's stack per iteration.
        """
        callee = self.functions[inner.name]
        argv = self._coerce_call_args(
            callee, [self._gen_transfer_value(a.value) for a in inner.arguments])
        slot = self._BLK_SLOT
        i32 = ir.IntType(32)
        if argv:
            array = self._entry_alloca(ir.ArrayType(slot, len(argv)),
                                       name="blkargs")
            for i, v in enumerate(argv):
                p = self.builder.gep(array,
                                     [ir.Constant(i32, 0), ir.Constant(i32, i)],
                                     name="blkargp")
                self.builder.store(self._blk_slot_write(v), p)
            slots = self.builder.ptrtoint(array, slot, name="blkargv")
        else:
            slots = ir.Constant(slot, 0)
        fnptr = self.builder.ptrtoint(self._blk_thunk(inner.name), slot,
                                      name="blkfn")
        return self.builder.call(
            self.functions["__saw_rt_offload_start"],
            [fnptr, slots, ir.Constant(slot, len(argv))], name="blkjob")

    def _generate_function_call(self, expr: FunctionCall):
        """Generate code for a function call.

        Handles regular functions, generic functions, closures, struct
        initialization, and built-in functions.
        """
        # design 22: `__saw_test_suspend()` is a synthetic suspension point for the
        # effect system. It has no runtime behavior — lower it to a no-op so
        # programs that use it still compile and run.
        # design 44: `__saw_suspend()` is the coroutine-transform state boundary. Any
        # `__saw_suspend` reaching codegen is one OUTSIDE a driven closure (the
        # transform rewrites the driven ones before codegen), so it too is a
        # no-op here — a lone `__saw_suspend` behaves like `__saw_test_suspend`.
        if expr.name in ("__saw_test_suspend", "__saw_suspend"):
            return None

        # Atomic construction (design 41 item 4): `Atomic(<int>)` builds the
        # `{ i64 }` cell value. The typechecker tagged this call.
        if expr.is_atomic_construct:
            atomic_saw = SawType(TypeKind.STRUCT, struct_name="Atomic",
                                 type_args=[SawType(TypeKind.INT)])
            atomic_llvm = self._get_llvm_type(atomic_saw)
            val = self._generate_expression(expr.arguments[0].value)
            cell = ir.Constant(atomic_llvm, ir.Undefined)
            return self.builder.insert_value(cell, val, 0, name="atomic_new")

        # Interior-cell construction (design 186): the cell IS its `T` (it is
        # layout-transparent), so wrapping a value emits the value.
        if expr.is_interior_cell_construct:
            return self._generate_expression(expr.arguments[0].value)

        # UnsafeMemory construction (design 46): the value IS the address (i64).
        if expr.is_unsafe_mem_construct:
            return self._generate_expression(expr.arguments[0].value)

        # Distinct alias construction (design 63): `UserId(42)`. An alias IS its
        # underlying — the distinction is the typechecker's alone — so there is
        # no conversion to emit, only the operand. The width coercion is the
        # same one a call argument gets: a bare literal arrives as the platform
        # word and an alias over a fixed-width underlying needs it narrowed.
        alias_name = expr.alias_construction
        if alias_name is not None:
            value = self._generate_expression(expr.arguments[0].value)
            target = self._get_llvm_type(
                SawType(TypeKind.STRUCT, struct_name=alias_name))
            if (isinstance(target, ir.IntType)
                    and isinstance(getattr(value, 'type', None), ir.IntType)
                    and value.type.width != target.width):
                return self._coerce_int_llvm(value, target)
            return value

        # Handle built-in print function
        if expr.name == "print":
            return self._generate_print(expr.arguments)

        # design 49: panic(message) / assert(cond, message) — route through the
        # saw_panic seam. Both terminate their block (panic unconditionally;
        # assert on the false branch) with `unreachable`.
        if expr.name == "panic":
            return self._generate_panic(expr)
        if expr.name == "assert":
            return self._generate_assert(expr)

        # Handle the spawn intrinsic: spawn { ... } -> Task<T>
        if expr.name == "spawn":
            return self._generate_spawn(expr)

        # Handle built-in sizeof<T>() function
        if expr.name == "sizeof":
            return self._generate_sizeof(expr)

        # Handle built-in alignof<T>() function
        if expr.name == "alignof":
            return self._generate_alignof(expr)

        # Handle the compiler-internal drop intrinsic __saw_deinit_in_place(ptr).
        # `ptr` is an UnsafePointer<T>; run drop glue for the T value it
        # addresses, in place. Used by stdlib container deinits (Vector/Map) to
        # release live elements before freeing the backing buffer. The
        # typechecker gates this to `deinit` bodies.
        if expr.name == "__saw_deinit_in_place":
            arg = expr.arguments[0].value
            ptr_val = self._generate_expression(arg)
            ptr_type = self._expr_type(arg)
            elem_type = ptr_type.inner_type
            if elem_type is not None and self._needs_cleanup(elem_type):
                self._emit_drop_at(ptr_val, elem_type)
            return None

        # design 45 (Part 0a): __saw_forget(optional_place) — clear an optional
        # lvalue's `is_some` discriminant to None WITHOUT dropping its inner
        # value. The coroutine transform emits this after a conditional `move` of
        # a cleanup-needing frame local so the frame's own Deinit (which drops the
        # field only when Some) skips the moved-out value: exactly-once cleanup on
        # every path. `Optional<T>` is laid out `{ i1 is_some, T }`; store 0 into
        # field 0. Reuses the same lvalue-pointer path as assignment.
        # design 45 item 4: the cooperative suspension primitives, when reached as
        # a plain call (a suspending function running straight through, i.e. NOT
        # under the executor transform — the transform removes them as state
        # boundaries). `yield_now()` is then a no-op; `sleep(ms)` still parks the
        # thread for real via the timer seam, so a hosted script's `sleep` is
        # honoured even without an executor.
        if expr.name in ("yield_now", "__saw_io_park"):
            return None
        # design 76 (A4): `io_wait(fd, dir)` reached OUTSIDE a coroutine frame (the
        # transform rewrites it to register+park inside a driven/spawned body).
        # With no executor to hand back to, register the fd and block the thread in
        # the reactor until it is ready — correct blocking semantics for a
        # non-cooperative caller.
        if expr.name == "io_wait":
            fd = self._generate_expression(expr.arguments[0].value)
            direction = self._generate_expression(expr.arguments[1].value)
            # design 118 stage 2: route the blocking-thread fallback (io_wait reached
            # OUTSIDE a coroutine frame, no executor to hand back to) through the SAME
            # Saw executor entry points the coroutine transform's io_wait lowering uses
            # — `__saw_exec_io_register` then `__saw_exec_park(-1)` — so stage 3 swaps
            # the reactor to the `Reactor` trait in ONE place, never at a synthesized
            # call site. design 91: no frame here, so register with a null token (the
            # poll skips null udata and returns when the fd is ready). The reactor
            # instance is injected inside the wrappers (design 117).
            self.builder.call(self.functions["__saw_exec_io_register"],
                              [fd, direction, ir.Constant(self.int_type, 0)])
            self.builder.call(self.functions["__saw_exec_park"],
                              [ir.Constant(self.int_type, -1)])
            return None
        # DF-134a: `io_unwait(fd, dir)` drops the readiness interest `io_wait`
        # armed. It never parks, so unlike `io_wait` there is no in-frame vs
        # outside-frame split — the same call is correct in both, and the coro
        # transform leaves it alone as ordinary body code (rewriting its argument
        # identifiers to frame fields like any other call).
        if expr.name == "io_unwait":
            fd = self._generate_expression(expr.arguments[0].value)
            direction = self._generate_expression(expr.arguments[1].value)
            self.builder.call(self.functions["__saw_exec_io_unregister"],
                              [fd, direction])
            return None
        # design 103 (A6) + 183: the blocking-extern offload intrinsics, emitted by
        # the coro transform when it lowers a `let x = slow(a, b)` blocking-extern
        # call. `__saw_blk_start(slow(a, b))` marshals the arguments into a slot
        # array and hands the runtime a THUNK plus that array; the other three are
        # thin one-arg wrappers over the runtime shims (done-poll / pipe fd /
        # join+take). All non-suspending: the SUSPENSION is the `io_wait` on the
        # job's pipe the transform emits between start and take.
        if expr.name == "__saw_blk_start":
            return self._gen_offload_start(expr.arguments[0].value)
        if expr.name in ("__saw_blk_done", "__saw_blk_pipe_fd", "__saw_blk_take"):
            shim = {"__saw_blk_done": "__saw_rt_offload_done",
                    "__saw_blk_pipe_fd": "__saw_rt_offload_pipe_fd",
                    "__saw_blk_take": "__saw_rt_offload_take"}[expr.name]
            job = self._generate_expression(expr.arguments[0].value)
            word = self.builder.call(self.functions[shim], [job], name="blkr")
            blk = expr.blk_extern
            if expr.name == "__saw_blk_take" and blk is not None:
                # design 183 unit 2: the job carries one result WORD; narrow it
                # back to the extern's declared return type (the inverse of what
                # the thunk widened). A Void/Never extern has no result to take.
                rt = self.functions[blk].function_type.return_type
                if isinstance(rt, ir.VoidType):
                    return None
                return self._blk_slot_read(word, rt)
            return word
        # The design-45 `sleep(ms)` primitive reached as a plain (non-suspending)
        # call — no executor to hand back to, so park the OS thread for real via the
        # timer seam. (design 118 stage 2: `__saw_exec_sleep_ns` is no longer an
        # intrinsic here — it is a real Saw function in std/taskgroup.saw over this
        # same seam, so it resolves through the ordinary call path.)
        if expr.name == "sleep":
            # design 180: the argument is a `Duration`, one u64 nanosecond field.
            # Read the field rather than calling `as_nanos` — this path is not
            # under the coroutine transform, so there is no re-typecheck to
            # resolve a synthesized method call against.
            dur = self._generate_expression(expr.arguments[0].value)
            ns = self.builder.extract_value(dur, 0, name="sleepns")
            self.builder.call(self.functions["__saw_rt_sleep_ns"], [ns])
            return None

        if expr.name == "__saw_forget":
            place = expr.arguments[0].value
            opt_ptr = self._get_lvalue_pointer(place)
            if opt_ptr is not None:
                i32 = ir.IntType(32)
                flag_ptr = self.builder.gep(
                    opt_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)],
                    name="forget_flag_ptr")
                self.builder.store(ir.Constant(ir.IntType(1), 0), flag_ptr)
            return None

        # design 158: `__saw_bt_table()` — the address of this program's
        # logical-backtrace table. A link-time constant; Saw cannot name an
        # extern global (DF-113a), so the walker reaches it through here.
        if expr.name == "__saw_bt_table":
            i32 = ir.IntType(32)
            gv = getattr(self, '_bt_table_global', None)
            if gv is None:
                return ir.Constant(ir.IntType(8).as_pointer(), None)
            return self.builder.gep(
                gv, [ir.Constant(i32, 0), ir.Constant(i32, 0)],
                inbounds=True, name="bt_table")

        # design 52b item 2: `__saw_box_data(&box)` — the data word (i8*) of a
        # `Box<any T>` fat pointer, i.e. the address of the erased heap payload.
        # `_generate_expression(&box)` is a pointer to the `{ i8* data, i8* vt }`
        # value; GEP field 0 and load it.
        if expr.name == "__saw_box_data":
            i32 = ir.IntType(32)
            box_ptr = self._generate_expression(expr.arguments[0].value)
            data_slot = self.builder.gep(
                box_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)],
                name="box_data_slot")
            return self.builder.load(data_slot, name="box_data")

        # design 52b item 3: `cancelled()` reached OUTSIDE a coroutine frame (the
        # transform rewrites it to the frame's `__cancel` word inside a driven /
        # spawned body). With no task to cancel, it is constant `false`.
        if expr.name == "cancelled":
            return ir.Constant(ir.IntType(1), 0)

        # Overloading (design 55): the typechecker resolved a concrete overload
        # and stamped its exact codegen symbol. Call that definition directly,
        # ahead of the struct-init / generic-instantiation routing (which keys on
        # the plain name and would otherwise mis-route an overloaded name).
        resolved_symbol = expr.resolved_symbol
        if resolved_symbol is not None and resolved_symbol in self.functions:
            func = self.functions[resolved_symbol]
            if expr.arg_plan is not None:
                args = self._planned_arg_values(
                    expr, self.func_defaults.get(resolved_symbol) or [])
            else:
                args = [self._gen_transfer_value(arg.value) for arg in expr.arguments]
                self._fill_func_defaults(args, resolved_symbol)
            return self.builder.call(func, self._coerce_call_args(func, args), name="calltmp")

        # Check if the name refers to a closure variable
        if expr.name in self.variables:
            closure_ptr = self.variables[expr.name]
            closure_val = self.builder.load(closure_ptr, name="closure")
            # Check if it's a closure struct { fn_ptr, env_ptr, dtor_ptr } (design 71)
            if isinstance(closure_val.type, ir.LiteralStructType) and len(closure_val.type.elements) == 3:
                # Call the closure
                fn_ptr = self.builder.extract_value(closure_val, 0, name="fn_ptr")
                env_ptr = self.builder.extract_value(closure_val, 1, name="env_ptr")
                arg_vals = [self._gen_transfer_value(arg.value) for arg in expr.arguments]
                return self.builder.call(fn_ptr, self._coerce_call_args(fn_ptr, [env_ptr] + arg_vals), name="closure_call")

        # `A()` where `A` is a type parameter bound to the concrete allocator in
        # the current monomorphization (design 37). Resolve `A` to its concrete
        # zero-sized allocator struct (e.g. `Global`, `LoudAlloc`) and construct
        # that — a zero-size placeholder over which `.alloc`/`.dealloc` dispatch
        # as direct calls, with no allocator value materialized at runtime.
        if expr.name in self.type_param_context:
            concrete = self.type_param_context[expr.name]
            if (concrete.kind == TypeKind.STRUCT and concrete.struct_name is not None
                    and (concrete.struct_name in self.generic_structs
                         or concrete.struct_name in self.struct_types)):
                field_inits = [(arg.name, arg.value) for arg in expr.arguments if arg.name]
                struct_init = StructInit(
                    struct_name=concrete.struct_name,
                    field_inits=field_inits,
                    type_args=concrete.type_args,
                    line=expr.line,
                    column=expr.column
                )
                return self._generate_struct_init(struct_init)

        # Check if this is actually a struct init (parser treats empty parens as function call)
        # Design 144: prefer the identity the typechecker resolved this name to.
        _sid = expr.resolved_type_identity or expr.name
        if _sid in self.generic_structs or _sid in self.struct_types:
            # Convert to struct init and generate that instead. Prefer the
            # typechecker's augmented field-init list (design 53: it includes any
            # init parameters filled from their defaults), falling back to the
            # raw named arguments.
            field_inits = expr.resolved_field_inits
            if field_inits is None:
                field_inits = [(arg.name, arg.value) for arg in expr.arguments if arg.name]
            struct_init = StructInit(
                struct_name=_sid,
                field_inits=field_inits,
                type_args=expr.type_args,
                line=expr.line,
                column=expr.column
            )
            # Carry the matched-init decision from typechecking (None = memberwise).
            struct_init.resolved_init_params = expr.resolved_init_params
            return self._generate_struct_init(struct_init)

        # Check if this is a call to a generic function. Design 105: a generic
        # overload winner carries its distinct `$OL$` base in `resolved_symbol`;
        # prefer it so the RIGHT template is instantiated (the plain name may map
        # to a sibling generic overload) and its instantiations stay collision-free.
        gen_name = expr.name
        rs = expr.resolved_symbol
        if rs is not None and rs in self.generic_functions:
            gen_name = rs
        if gen_name in self.generic_functions:
            if not expr.type_args:
                raise ValueError(
                    f"Generic function {expr.name} requires type arguments. "
                    f"Use {expr.name}<Type>(...)"
                )
            # Instantiate the generic function. Inside an enclosing generic body
            # the type args may be the enclosing template's own params (design 77
            # item 2: `inner<T>(w)` in `middle<T: Seed>`), so substitute them
            # through this monomorphization's context (T -> Acorn) before
            # mangling — otherwise we'd try to instantiate over the abstract `T`
            # and recurse without ever resolving it.
            call_type_args = [
                self._substitute_saw_type(ta, self.type_param_context)
                for ta in expr.type_args
            ]
            mangled_name = self._instantiate_generic_function(gen_name, call_type_args)
            func = self.functions[mangled_name]
            # Design 108: a generic instantiation registers its default values
            # under the MANGLED name (`f$1$Int`), not the plain call name, so the
            # default-fill below must key by it — otherwise an omitted trailing
            # default (`f<Int>(1)` for `f<T>(a, b: T = 0)`) is never materialized
            # and the call is emitted with too few args (an llvmlite ICE).
            defaults_key = mangled_name
        else:
            # Look up regular user-defined function
            if expr.name not in self.functions:
                raise ValueError(f"Undefined function: {expr.name}")
            func = self.functions[expr.name]
            defaults_key = expr.name

        # Arguments are now Argument objects with .value
        if expr.arg_plan is not None:
            # Design 66: labeled/mid-skip call — emit args by the binding plan,
            # interleaving default-filled parameter slots.
            args = self._planned_arg_values(
                expr, self.func_defaults.get(defaults_key) or [])
        else:
            args = [self._gen_transfer_value(arg.value) for arg in expr.arguments]
            # Fill omitted trailing arguments from their default expressions (design 53).
            self._fill_func_defaults(args, defaults_key)
        # design 118 stage 3: the compiler no longer injects the reactor instance —
        # the executor threads it explicitly through `SystemReactor` (std/taskgroup.saw),
        # so every reactor seam call site already passes the instance as arg 0.
        result = self.builder.call(func, self._coerce_call_args(func, args), name="calltmp")
        if self._terminate_after_noreturn(func):
            return None

        # Wrap result in optional for extern functions that return nullable pointers
        if expr.name in self.extern_optional_returns:
            inner_type = self.extern_optional_returns[expr.name]
            optional_type = self._get_llvm_type(SawType(TypeKind.OPTIONAL, inner_type=inner_type))
            # Check if pointer is NULL
            null_ptr = ir.Constant(result.type, None)
            is_not_null = self.builder.icmp_unsigned('!=', result, null_ptr, name="is_not_null")
            # Build optional struct: {i1 is_some, T value}
            opt_val = ir.Constant(optional_type, ir.Undefined)
            opt_val = self.builder.insert_value(opt_val, is_not_null, 0, name="opt_flag")
            opt_val = self.builder.insert_value(opt_val, result, 1, name="opt_val")
            return opt_val

        return result

    def _terminate_after_noreturn(self, callee) -> bool:
        """Terminate the current block when `callee` is a `-> Never` function.

        A `-> Never` declaration is emitted as `void` + `noreturn` (design 58),
        so control does not continue past a call to it — the same fact an inline
        `panic(...)` has, and it needs the same `unreachable`. Without it the
        `call`'s VOID value flowed on as if it were a result and reached the
        caller's `ret` against a real return type, which nothing but the LLVM IR
        parser objected to ("value doesn't match function result type"), and it
        surfaced as an uncaught compiler crash rather than any diagnostic.
        Design 177 makes a diverging function writable without a panic in it, so
        this stopped being a corner nobody reached.

        Returns True when the block was terminated (the caller must then hand
        back None, exactly as `_generate_panic` does).
        """
        if "noreturn" not in getattr(callee, "attributes", ()):
            return False
        self.builder.unreachable()
        return True

    def _raw_bytes_ptr(self, data: str):
        """Private global holding exactly `data`'s bytes (no added NUL).

        Returns (i8* pointer-to-first-byte, i64 length). Used by print to feed
        saw_write(ptr, len) directly, so the emitted byte count is exact.
        """
        cache = getattr(self, "_raw_byte_globals", None)
        if cache is None:
            cache = {}
            self._raw_byte_globals = cache
        encoded = data.encode("utf-8")
        if data not in cache:
            arr_type = ir.ArrayType(ir.IntType(8), len(encoded))
            # design 168 unit 3 (DF-164c): content-named, like `.sawstr`. It
            # shared `string_counter` with the string literals, so a print format
            # piece anywhere renumbered every one of them.
            g = ir.GlobalVariable(self.module, arr_type,
                                  name=self._synth_symbol(
                                      f".rawbytes.{content_tag(encoded)}"))
            g.linkage = "private"
            g.global_constant = True
            g.initializer = ir.Constant(arr_type, bytearray(encoded))
            cache[data] = g
        g = cache[data]
        zero = ir.Constant(ir.IntType(32), 0)
        ptr = self.builder.gep(g, [zero, zero], inbounds=True)
        # Length feeds the platform-width saw_write seam (design 47).
        return ptr, ir.Constant(self.int_type, len(encoded))

    def visit_PreparedValue(self, expr):
        """Yield the LLVM value a `PreparedValue` was built around."""
        return expr.value

    # Bytes of stack scratch a single `{}` rendering of a user `Printable` value
    # is given. Its `format` streams into a FIXED StringBuilder over this, so a
    # value that renders longer is cut and marked rather than allocating.
    PRINTABLE_SCRATCH = 512

    def _format_pieces(self, fmt_expr, value_args):
        """Interleave a checked format string's literal parts with its arguments.

        Yields `("text", str)` and `("arg", Expression)` in output order. The
        typechecker has already established that the format string is a literal
        and that its `{}` count matches `value_args`, so this is pure shape.
        """
        if isinstance(fmt_expr, StringInterpolation):
            parts = fmt_expr.parts
        else:
            parts = [fmt_expr.value]
        for i, part in enumerate(parts):
            if part:
                yield ("text", part)
            if i < len(value_args):
                yield ("arg", value_args[i].value)

    def _format_segments(self, fmt_expr, value_args):
        """Lower a format call to a list of `(i8* ptr, word len)` byte ranges.

        Design 137. Nothing here allocates: literal parts are interned byte
        constants, a String argument is its own bytes, an integer is rendered by
        `__saw_fmt_int` into stack scratch, and a user `Printable` streams
        through its own `format` into a fixed StringBuilder over stack scratch.
        The caller decides what to do with the ranges — `print` writes them
        straight to the output seam, `panic` concatenates them into its message
        buffer — so ONE walk serves both and the two cannot drift.
        """
        segments = []
        for kind, item in self._format_pieces(fmt_expr, value_args):
            if kind == "text":
                segments.append(self._raw_bytes_ptr(item))
            else:
                segments.append(self._render_argument(item))
        return segments

    def _render_argument(self, arg_expr):
        """Render one format argument to a `(i8* ptr, word len)` byte range."""
        word = self.int_type
        i8 = ir.IntType(8)

        saw_type = arg_expr.resolved_type
        if saw_type is not None and self.type_param_context:
            saw_type = saw_type.substitute(self.type_param_context)
        if saw_type is not None:
            saw_type = self._resolve_type_alias(saw_type)

        # A user struct/enum, or an erased `&any Printable`/`Box<any Error>`:
        # stream it through `format` into a fixed builder over stack scratch.
        # `to_string()` would be shorter and is what interpolation does, but it
        # returns an owned String — an allocation, which is the one thing this
        # path may not do.
        if (saw_type is not None
                and self.namespace.is_printable(saw_type)
                and not self._is_builtin_interp_type(saw_type)):
            return self._render_via_format(arg_expr, saw_type)

        value = self._generate_expression(arg_expr)

        if isinstance(value.type, ir.PointerType):
            # String: its own bytes, at its header length.
            length = self.builder.call(self.functions["__saw_string_len"],
                                       [value], name="fmt_str_len")
            return (value, length)

        if isinstance(value.type, ir.IntType):
            if value.type.width == 1:
                true_ptr, true_len = self._raw_bytes_ptr("true")
                false_ptr, false_len = self._raw_bytes_ptr("false")
                return (self.builder.select(value, true_ptr, false_ptr),
                        self.builder.select(value, true_len, false_len))
            unsigned_kinds = {TypeKind.UINT, TypeKind.UINT8, TypeKind.UINT16,
                              TypeKind.UINT32, TypeKind.UINT64}
            is_unsigned = bool(saw_type is not None
                               and saw_type.kind in unsigned_kinds)
            return self._render_int_value(value, is_unsigned)

        if isinstance(value.type, ir.DoubleType):
            # Float stays snprintf-based, into stack scratch (hosted only —
            # freestanding rejects it at typecheck, as `print` already did).
            c_ptr = self._value_to_string(value, saw_type)
            strlen_fn = self._libc_func("strlen", word, [i8.as_pointer()])
            return (c_ptr, self.builder.call(strlen_fn, [c_ptr], name="fmt_f_len"))

        raise ValueError(f"Cannot format type: {value.type}")

    def _render_int_value(self, value, is_unsigned: bool, in_entry: bool = True):
        """Render an integer LLVM value to a `(i8* ptr, word len)` byte range.

        Brings the value to the platform width with the same extension `print`
        uses and renders it with the same itoa, so `print(n)`, `print("{}", n)`
        and a checked cast's panic message all agree byte for byte — including
        across the whole unsigned range, which is what `__saw_fmt_uint` is for.

        `in_entry` places the digit scratch in the entry block, which is right
        for a format argument on the normal path (the buffer is live while the
        segments are consumed). A panic block passes False: that block ends in
        `unreachable`, so its scratch cannot be re-entered, and a function that
        merely CONTAINS a checked cast should not pay frame bytes for it —
        the same reasoning `_emit_runtime_panic` applies to its own buffer.
        """
        word = self.int_type
        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        if value.type.width < self.int_width:
            if is_unsigned:
                value = self.builder.zext(value, word, name="fmt_ext")
            else:
                value = self.builder.sext(value, word, name="fmt_ext")
        elif value.type.width > self.int_width:
            value = self.builder.trunc(value, word, name="fmt_trunc")
        buf_type = ir.ArrayType(i8, self.INT_FMT_MAX)
        buf = (self._entry_alloca(buf_type, name="fmt_int_buf") if in_entry
               else self.builder.alloca(buf_type, name="fmt_int_buf"))
        bufp = self.builder.gep(buf, [ir.Constant(i32, 0), ir.Constant(i32, 0)],
                                inbounds=True)
        fmt_fn = "__saw_fmt_uint" if is_unsigned else "__saw_fmt_int"
        length = self.builder.call(self.functions[fmt_fn], [value, bufp],
                                   name="fmt_int_len")
        return (bufp, length)

    def _render_via_format(self, arg_expr, saw_type):
        """Stream a `Printable` value through `format` into stack scratch.

        Builds a FIXED `StringBuilder` (design 137) over a stack buffer and
        hands it to the value's own `format(into:)`, then reports how many bytes
        landed. The builder truncates rather than growing, so a value that
        renders longer than `PRINTABLE_SCRATCH` ends in the `…` marker — the one
        place this path is bounded, and it says so.
        """
        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        word = self.int_type

        scratch = self._entry_alloca(ir.ArrayType(i8, self.PRINTABLE_SCRATCH),
                                     name="fmt_scratch")
        scratch_ptr = self.builder.gep(
            scratch, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)

        sb_type, sb_fields = self.struct_types["StringBuilder"]
        sb_ptr = self._entry_alloca(sb_type, name="fmt_sb")

        def field(name):
            return self.builder.gep(
                sb_ptr, [ir.Constant(i32, 0),
                         ir.Constant(i32, sb_fields.index(name))],
                inbounds=True, name=f"sb_{name}")

        # `buffer` is `UnsafePointer<Int8>?` — the {i1 is_some, ptr} pair.
        buf_slot = field("buffer")
        opt_type = buf_slot.type.pointee
        opt = ir.Constant(opt_type, ir.Undefined)
        opt = self.builder.insert_value(opt, ir.Constant(ir.IntType(1), 1), 0)
        opt = self.builder.insert_value(opt, scratch_ptr, 1)
        self.builder.store(opt, buf_slot)
        self.builder.store(ir.Constant(word, 0), field("length"))
        self.builder.store(ir.Constant(word, self.PRINTABLE_SCRATCH),
                           field("capacity"))
        self.builder.store(ir.Constant(ir.IntType(1), 1), field("fixed"))
        self.builder.store(ir.Constant(ir.IntType(1), 0), field("truncated"))
        self.builder.store(ir.Constant(i8, 0), scratch_ptr)

        call = MethodCall(
            object=arg_expr, method_name="format",
            arguments=[Argument(name="into", value=PreparedValue(sb_ptr))],
            line=arg_expr.line,
            column=arg_expr.column)
        self._generate_expression(call)

        length = self.builder.load(field("length"), name="fmt_sb_len")
        return (scratch_ptr, length)

    def _generate_print(self, arguments: List[Argument]):
        """Generate code for the print built-in function.

        Int family / Bool / String / interpolation all lower to saw_write (the
        output seam); only Float remains printf-based (dtoa is out of scope).
        Both paths share C stdio in the hosted profile, so mixed int/float print
        output keeps its exact order and formatting.
        """
        saw_write = self.functions["__saw_rt_write"]
        # print() is a Void builtin, but it is frequently the tail expression of
        # an if/match branch; the conditional lowering unifies branch values with
        # a phi. The old printf path yielded an i32, so keep returning an i32 (a
        # discarded dummy) to preserve that structure rather than a void value
        # (which would produce an illegal `phi void`).
        dummy = ir.Constant(ir.IntType(32), 0)

        if not arguments:
            # Print a bare newline.
            nl_ptr, nl_len = self._raw_bytes_ptr("\n")
            self.builder.call(saw_write, [nl_ptr, nl_len])
            return dummy

        if len(arguments) > 1:
            # design 137: `print("x = {}", x)`. Each segment goes straight to
            # the output seam at its own length, so a long String argument is
            # written WHOLE — the line has no capacity limit, and the only
            # bounded piece is a single user `Printable` rendering.
            for seg_ptr, seg_len in self._format_segments(arguments[0].value,
                                                          arguments[1:]):
                self.builder.call(saw_write, [seg_ptr, seg_len])
            nl_ptr, nl_len = self._raw_bytes_ptr("\n")
            self.builder.call(saw_write, [nl_ptr, nl_len])
            return dummy

        # Arguments are Argument objects with .value
        arg = arguments[0]
        # Printable (design 56): a non-builtin Printable argument is rendered via
        # its `to_string()` and printed as a String; builtins keep their fast
        # path below (byte-identical). Non-Printable non-builtins fall through to
        # the existing "cannot print" error.
        # Read the annotation defensively (getattr, not _expr_type): a
        # module-qualified expression can reach codegen without a resolved_type
        # (the pre-existing L6 gap), and print of such a value must keep working
        # via its LLVM value type below — not ICE.
        arg_saw = arg.value.resolved_type
        if arg_saw is not None and self.type_param_context:
            arg_saw = arg_saw.substitute(self.type_param_context)
        if arg_saw is not None:
            arg_saw = self._resolve_type_alias(arg_saw)
        # A non-builtin Printable value (user struct/enum, or an erased
        # `&any Printable`/`Box<any Error>`) is rendered via `to_string()`;
        # builtins and non-Printable values keep the paths below.
        if (arg_saw is not None
                and self.namespace.is_printable(arg_saw)
                and not self._is_builtin_interp_type(arg_saw)):
            mc = MethodCall(object=arg.value, method_name="to_string",
                            arguments=[], line=0, column=0)
            mc.resolved_type = SawType(TypeKind.STRING)
            value = self._generate_expression(mc)
        else:
            value = self._generate_expression(arg.value)

        if isinstance(value.type, ir.IntType):
            if value.type.width == 1:
                # Bool -> "true\n" / "false\n" via one saw_write.
                true_ptr, true_len = self._raw_bytes_ptr("true\n")
                false_ptr, false_len = self._raw_bytes_ptr("false\n")
                str_ptr = self.builder.select(value, true_ptr, false_ptr)
                str_len = self.builder.select(value, true_len, false_len)
                self.builder.call(saw_write, [str_ptr, str_len])
            else:
                # Integer family: bring the value to the platform Int width
                # (design 47) with exactly the sign-/zero-extension the old printf
                # %lld path used (sext signed, zext unsigned), then format via the
                # width-parametric itoa. On a 64-bit target this is the pre-47 i64
                # path unchanged; on riscv32 it formats at 32 bits (no __udivdi3).
                #
                # The FORMATTER is chosen by the operand's kind, not just the
                # extension (design 122 unit G / DF-119b): a same-width unsigned
                # value has nothing to zero-extend, so it used to reach the signed
                # formatter unchanged and `print(UInt.max)` emitted `-1`.
                # Interpolation always picked `%llu` here, so the two disagreed.
                iw = self.int_width
                # `arg_saw` is read defensively above; only fall back to
                # `_expr_type` on the narrow path that already did (it ICEs on a
                # module-qualified expression that reached codegen unannotated —
                # the pre-existing L6 gap).
                saw_type = arg_saw
                if saw_type is None and value.type.width < iw:
                    saw_type = self._expr_type(arg.value)
                unsigned_kinds = {TypeKind.UINT, TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64}
                is_unsigned = bool(saw_type is not None
                                   and saw_type.kind in unsigned_kinds)
                if value.type.width < iw:
                    if is_unsigned:
                        value = self.builder.zext(value, self.int_type, name="print_ext")
                    else:
                        value = self.builder.sext(value, self.int_type, name="print_ext")
                elif value.type.width > iw:
                    value = self.builder.trunc(value, self.int_type, name="print_trunc")
                fmt_fn = "__saw_print_uint" if is_unsigned else "__saw_print_int"
                self.builder.call(self.functions[fmt_fn], [value])

        elif isinstance(value.type, ir.DoubleType):
            # Float stays printf-based (identical %f formatting; shares stdio with
            # saw_write's hosted default). Freestanding rejects this at typecheck.
            fmt = self._create_string_constant("%f\n")
            zero = ir.Constant(ir.IntType(32), 0)
            fmt_ptr = self.builder.gep(fmt, [zero, zero], inbounds=True)
            self.builder.call(self.printf, [fmt_ptr, value])

        elif isinstance(value.type, ir.PointerType):
            # String: write the exact byte range (ptr + header len), then newline.
            str_len = self.builder.call(self.functions["__saw_string_len"], [value])
            self.builder.call(saw_write, [value, str_len])
            nl_ptr, nl_len = self._raw_bytes_ptr("\n")
            self.builder.call(saw_write, [nl_ptr, nl_len])

        else:
            raise ValueError(f"Cannot print type: {value.type}")

        return dummy

    # A panic message is assembled in this many bytes of stack (design 137).
    # Four are reserved — three for the truncation marker, one for the trailing
    # newline — so a message of PANIC_SCRATCH - 4 bytes survives whole and
    # anything longer is cut and marked.
    PANIC_SCRATCH = 512
    TRUNCATION_MARKER = "…"

    def _emit_runtime_panic(self, segments):
        """Assemble `segments` into one contiguous buffer and abort via saw_panic.

        `segments` is a list of `(i8* ptr, word len)` byte ranges. They are
        concatenated into a STACK buffer and handed to the `saw_panic(msg, len)`
        seam in a single call, so a freestanding handler receives the whole
        message. A trailing newline is appended here; callers pass the message
        parts only. `unreachable` terminates the block. Nothing is freed:
        control never returns.

        Design 137: this used to concatenate into a `__saw_string_alloc` block,
        which made reporting a panic depend on the allocator. That is exactly
        backwards for the failure this language leans on — a `Vector.push` that
        panics BECAUSE the allocator refused could not then assemble the message
        saying so, and design 123 had to give its test seam a deny WINDOW so the
        panic path could allocate after the allocation under test was refused.
        The buffer is a stack array now, so the message survives total allocator
        denial, the freestanding profile, and a kernel with no heap at all.

        Bounded storage means a long message is cut. It is cut VISIBLY: the
        trailing `…` says the reader is not looking at the whole thing. The cut
        lands on a byte boundary, which can split a multi-byte scalar — the
        marker is still stamped, so the message stays self-describing.

        The scratch is allocated in the panicking block rather than the entry
        block on purpose: the block ends in `unreachable`, so it cannot be
        re-entered, and a function that merely CONTAINS a panic pays no stack
        for it.
        """
        word = self.int_type
        i8 = ir.IntType(8)
        i8ptr = i8.as_pointer()
        i32 = ir.IntType(32)
        memcpy_fn = self._libc_func("memcpy", i8ptr, [i8ptr, i8ptr, word])

        marker_len = len(self.TRUNCATION_MARKER.encode("utf-8"))
        text_max = self.PANIC_SCRATCH - marker_len - 1   # marker + '\n'

        buf = self.builder.alloca(ir.ArrayType(i8, self.PANIC_SCRATCH),
                                  name="panic_buf")
        base = self.builder.gep(buf, [ir.Constant(i32, 0), ir.Constant(i32, 0)],
                                inbounds=True, name="panic_base")

        limit = ir.Constant(word, text_max)
        offset = ir.Constant(word, 0)
        truncated = ir.Constant(ir.IntType(1), 0)
        for seg_ptr, seg_len in segments:
            room = self.builder.sub(limit, offset, name="panic_room")
            over = self.builder.icmp_unsigned('>', seg_len, room, name="panic_over")
            take = self.builder.select(over, room, seg_len, name="panic_take")
            dst = self.builder.gep(base, [offset], inbounds=True, name="panic_seg")
            self.builder.call(memcpy_fn, [dst, seg_ptr, take])
            offset = self.builder.add(offset, take, name="panic_off")
            truncated = self.builder.or_(truncated, over, name="panic_trunc")

        # Stamp the marker only when something was dropped: a zero-length copy
        # is the no-op branch, so this stays straight-line code in a block that
        # must end in `unreachable`.
        mark_ptr, mark_len = self._raw_bytes_ptr(self.TRUNCATION_MARKER)
        stamp = self.builder.select(truncated, mark_len, ir.Constant(word, 0),
                                    name="panic_stamp")
        self.builder.call(memcpy_fn, [
            self.builder.gep(base, [offset], inbounds=True, name="panic_mark"),
            mark_ptr, stamp])
        offset = self.builder.add(offset, stamp, name="panic_marked")

        self.builder.store(ir.Constant(i8, ord('\n')),
                           self.builder.gep(base, [offset], inbounds=True,
                                            name="panic_nl"))
        total = self.builder.add(offset, ir.Constant(word, 1), name="panic_total")
        self.builder.call(self._panic_sink(), [base, total])
        self.builder.unreachable()

    def _panic_location_prefix(self, line: int) -> str:
        """The unified `panic at FILE:LINE: ` message prefix (design 69).

        FILE is the current function's source basename (from debug-info state);
        LINE is the call-site line (a compile-time constant). Both panic() and
        assert() share this so a runtime abort names its source location even
        without a debugger attached. Falls back to `panic: ` when no source is
        known (e.g. a synthesized call site)."""
        base = self._di_current_basename()
        if base and line:
            return f"panic at {base}:{line}: "
        if line:
            return f"panic at line {line}: "
        return "panic: "

    def _generate_panic(self, expr: FunctionCall):
        """panic(message: String) -> Never (design 49 item 1).

        Emits `panic at FILE:LINE: {message}\\n` through the saw_panic seam
        (design 69 unified format), then terminates the block. Returns None
        (the value is NEVER; nothing consumes it).
        """
        prefix_ptr, prefix_len = self._raw_bytes_ptr(
            self._panic_location_prefix(expr.line))
        if len(expr.arguments) > 1:
            # design 137: `panic("out of {}", what)`.
            segments = self._format_segments(expr.arguments[0].value,
                                             expr.arguments[1:])
            self._emit_runtime_panic([(prefix_ptr, prefix_len)] + segments)
            return None
        msg_val = self._generate_expression(expr.arguments[0].value)
        msg_len = self.builder.call(self.functions["__saw_string_len"], [msg_val],
                                    name="panic_msg_len")
        self._emit_runtime_panic([(prefix_ptr, prefix_len),
                                  (msg_val, msg_len)])
        return None

    def _generate_assert(self, expr: FunctionCall):
        """assert(cond: Bool, message: String) (design 49 item 2).

        A no-op when `cond` is true. On false it panics with the design-69
        unified format "panic at FILE:LINE: assertion failed: {message}\\n" —
        the call-site FILE:LINE is a compile-time constant. The message is
        evaluated only on the failing branch.
        """
        cond = self._generate_expression(expr.arguments[0].value)
        func = self.builder.function
        fail_bb = func.append_basic_block("assert_fail")
        cont_bb = func.append_basic_block("assert_cont")
        self.builder.cbranch(cond, cont_bb, fail_bb)

        self.builder.position_at_end(fail_bb)
        prefix_ptr, prefix_len = self._raw_bytes_ptr(
            self._panic_location_prefix(expr.line) + "assertion failed: ")
        if len(expr.arguments) > 2:
            # design 137: `assert(ok, "want {} got {}", a, b)`. The arguments are
            # rendered on THIS branch only, so a passing assert costs nothing.
            segments = self._format_segments(expr.arguments[1].value,
                                             expr.arguments[2:])
            self._emit_runtime_panic([(prefix_ptr, prefix_len)] + segments)
        else:
            msg_val = self._generate_expression(expr.arguments[1].value)
            msg_len = self.builder.call(self.functions["__saw_string_len"],
                                        [msg_val], name="assert_msg_len")
            self._emit_runtime_panic([(prefix_ptr, prefix_len),
                                      (msg_val, msg_len)])

        self.builder.position_at_end(cont_bb)
        return None

    def _generate_sizeof(self, expr: FunctionCall):
        """Generate code for sizeof<T>() - returns the size in bytes of type T."""
        # Get the type argument
        if not expr.type_args or len(expr.type_args) != 1:
            raise ValueError("sizeof requires exactly one type argument")

        saw_type = expr.type_args[0]
        # Resolve type parameters if in a generic context
        if saw_type.kind == TypeKind.STRUCT and saw_type.struct_name in self.type_param_context:
            saw_type = self.type_param_context[saw_type.struct_name]
        llvm_type = self._get_llvm_type(saw_type)
        # `sizeof<Void>()` is 0 (Void is the zero-size type; it reaches here via a
        # Void-result Task control block, design 77 item 1). LLVM has no ABI size
        # for `void`, so fold it directly.
        size = 0 if isinstance(llvm_type, ir.VoidType) else self._abi_size(llvm_type)
        return ir.Constant(self.int_type, size)  # sizeof<T>() -> platform Int

    def _generate_alignof(self, expr: FunctionCall):
        """Generate code for alignof<T>() - returns the ABI alignment of T in bytes.

        Sibling of _generate_sizeof: resolves the single type argument (through
        the monomorphization type-param context, so a generic `T` folds to its
        concrete instantiation) and emits the target's ABI alignment for that
        LLVM type as an i64 constant.
        """
        if not expr.type_args or len(expr.type_args) != 1:
            raise ValueError("alignof requires exactly one type argument")

        saw_type = expr.type_args[0]
        # Resolve type parameters if in a generic context
        if saw_type.kind == TypeKind.STRUCT and saw_type.struct_name in self.type_param_context:
            saw_type = self.type_param_context[saw_type.struct_name]
        llvm_type = self._get_llvm_type(saw_type)
        align = self._abi_align(llvm_type)
        return ir.Constant(self.int_type, align)  # alignof<T>() -> platform Int

    def _generate_enum_from_raw(self, expr, enum_name: str):
        """Lower `E.from(raw: u)` for a raw-backed enum (design 145 unit B2).

        A chain of selects over the declared values: the result is `Some(case)`
        for a value that names one and `None` otherwise. No branching and no
        trap — an unrecognized wire byte is data the caller decides about.
        """
        llvm_enum_type, variant_tags, _ = self.enum_types[enum_name]
        raw = self._generate_expression(expr.arguments[0].value)

        optional_type = ir.LiteralStructType([ir.IntType(1), llvm_enum_type])
        result = ir.Constant(optional_type, ir.Undefined)
        result = self.builder.insert_value(
            result, ir.Constant(ir.IntType(1), 0), 0, name="from_raw_none")
        # Give the None path a defined payload too: reading it is already gated
        # by the flag, and leaving `undef` there is a needless poison source.
        result = self.builder.insert_value(
            result, ir.Constant(llvm_enum_type, 0), 1)

        # Sorted so the emitted IR is deterministic regardless of dict order.
        for variant_name in sorted(variant_tags):
            tag = variant_tags[variant_name]
            hit = self.builder.icmp_signed(
                '==', raw, ir.Constant(llvm_enum_type, tag),
                name=f"from_raw_is_{variant_name}")
            some = self.builder.insert_value(
                result, ir.Constant(ir.IntType(1), 1), 0)
            some = self.builder.insert_value(
                some, ir.Constant(llvm_enum_type, tag), 1)
            result = self.builder.select(hit, some, result,
                                         name=f"from_raw_sel_{variant_name}")
        return result

    def _generate_method_call(self, expr: MethodCall, receiver_ptr=None):
        """Generate code for method call, static method call, enum initialization, or module function call.

        `receiver_ptr` (design 111 optional chaining): when set, the instance
        receiver is this precomputed pointer to the payload struct — the caller
        (the optional-chain lowering) already unwrapped the payload in place, so
        the object sub-expression is NOT re-evaluated and the mid-chain receiver is
        borrowed, never spilled/copied.

        The parser creates MethodCall for all these cases:
        - object.method(args) - instance method call
        - StructName.method(args) - static method call
        - EnumType.Variant(args) - enum variant initialization
        - ModuleName.function(args) - module function call (Phase 2)
        """
        # design 51: erased-direct `Box<any Trait>.make(v)` construction, and
        # dynamic dispatch through a `&any Trait` / `Box<any Trait>` receiver. Both
        # are tagged by the typechecker.
        if expr.erased_box_make is not None:
            return self._generate_erased_box_make(expr)
        if expr.existential_dispatch is not None:
            return self._generate_existential_method_call(expr, expr.existential_dispatch)

        # Fixed-array builtins (design 72 L12/M1): the typechecker tagged the node.
        if expr.array_builtin is not None:
            return self._generate_array_builtin(expr)

        # `o.take()` (design 131): the consuming payload read.
        if expr.optional_take:
            return self._generate_optional_take(expr)

        # `o.is_some()` / `o.is_none()` (DF-218a): the tag-only presence reads.
        if expr.optional_presence is not None:
            return self._generate_optional_presence(expr)

        # Erased-box downcasting `b.is<T>()` / `b.take<T>()` (design 72). `take`
        # consumes the box: clear the receiver binding's drop flag (like a move)
        # so scope-exit teardown does not double-free the shell take already freed.
        if expr.erased_downcast is not None:
            if (expr.erased_downcast['op'] == "take"
                    and isinstance(expr.object, Identifier)):
                name = expr.object.name
                flag = self.drop_flags.get(name)
                if flag is not None:
                    self.builder.store(ir.Constant(ir.IntType(1), 0), flag)
                self.moved_variables.add(name)
            return self._generate_erased_downcast(expr)

        # Arc payload-method forwarding (design 21b E2): the typechecker resolved
        # this as an immutable `&self` method on Arc's payload; forward through a
        # borrow of the control block's payload slot.
        if expr.arc_forward_payload_type is not None:
            return self._generate_arc_forward_call(expr)

        # Box payload-method forwarding (design 42 item 1): the typechecker
        # resolved this as an immutable `&self` method on Box's payload; forward
        # through a borrow of the heap payload at `ptr[0]`.
        if expr.box_forward_payload_type is not None:
            return self._generate_box_forward_call(expr)

        # A call through a function-typed struct field (design 24 item 3): the
        # typechecker resolved `obj.field(args)` as an indirect closure call.
        if expr.is_field_call:
            return self._generate_field_call(expr)

        # Atomic<Int> methods (design 41 item 4): lowered directly to seq_cst
        # LLVM atomics on the cell, bypassing the (dead) stub method bodies.
        # Interior mutability is the sanctioned mutation path — this fires on a
        # METHOD call, never touching the item-2 no-assignment rule.
        recv_saw = expr.object.resolved_type
        if (recv_saw is not None and recv_saw.kind == TypeKind.STRUCT
                and recv_saw.struct_name == "Atomic"
                and expr.method_name in ("load", "store", "fetch_add", "compare_exchange")):
            return self._generate_atomic_method(expr, recv_saw)

        # design 186: `cell.ptr()` — the address of the cell's own storage. The
        # cell is layout-transparent, so that address IS the receiver's, which
        # is why this reuses the Atomic receiver walk (both need the CALLER's
        # storage, never a spilled copy) and skips its final field GEP.
        if expr.interior_cell_ptr:
            result_saw = expr.resolved_type
            payload_llvm = (self._get_llvm_type(result_saw.inner_type)
                            if result_saw is not None
                            and result_saw.inner_type is not None else None)
            return self._interior_cell_pointer(expr.object, payload_llvm)

        # UnsafeMemory accessors (design 46): read/write (volatile on Device) and
        # the Normal region accessors ptr/len/end. The typechecker tagged the node.
        if expr.um_method is not None:
            return self._generate_um_method(expr)

        # Check if this is a nested module function call: Parent.Child.symbol(args)
        if isinstance(expr.object, MemberAccess):
            # Check if it's a chain of module accesses
            inner_module_sym = self._resolve_module_chain(expr.object)
            if inner_module_sym and inner_module_sym.namespace:
                from namespace import SymbolKind
                symbol = inner_module_sym.namespace.resolve(expr.method_name)
                if symbol and symbol.kind == SymbolKind.FUNCTION:
                    # Generate a direct function call (all modules are merged)
                    return self._generate_module_function_call(expr)
                elif symbol and symbol.kind == SymbolKind.STRUCT:
                    # Generate struct initialization
                    return self._generate_module_struct_init(expr)

            # Check if it's module.Struct.static_method()
            # The MemberAccess resolves to a struct type (not a module)
            resolved_struct = getattr(expr.object, 'resolved_struct_name', None)
            if resolved_struct:
                # This is a static method call on a module-qualified struct
                if self.namespace.is_static_method(resolved_struct, expr.method_name):
                    return self._generate_static_method_call(expr, resolved_struct)

        # Check if this is a module function call or struct init: ModuleName.symbol(args)
        # Design 150 pin 4: module qualifiers are WEAK — a local of the same name
        # wins, so `data.push(x)` beside `import std.data` is a method call on the
        # local. The typechecker resolved it that way; codegen must agree.
        if isinstance(expr.object, Identifier) and expr.object.name not in self.variables:
            if expr.object.name in self.namespace.modules:
                module_sym = self.namespace.modules[expr.object.name]
                if module_sym.namespace:
                    from namespace import SymbolKind
                    symbol = module_sym.namespace.resolve(expr.method_name)
                    if symbol and symbol.kind == SymbolKind.FUNCTION:
                        # Generate a direct function call (all modules are merged)
                        return self._generate_module_function_call(expr)
                    elif symbol and symbol.kind == SymbolKind.STRUCT:
                        # Generate struct initialization
                        return self._generate_module_struct_init(expr)

        # Design 145 unit B2: `E.from(raw: u)` on a raw-backed enum. The
        # typechecker stamped the enum when it resolved this as the synthesized
        # lookup, so there is no symbol to call — it lowers inline.
        from_raw_enum = expr.enum_from_raw
        if from_raw_enum is not None:
            return self._generate_enum_from_raw(expr, from_raw_enum)

        # Design 170: `UInt8.from(x)` / `UInt8.from(truncating: x)`. An integer
        # type name is not a struct, so there is no symbol to call — the
        # typechecker's plan is the whole lowering.
        int_from = expr.int_from
        if int_from is not None:
            return self._generate_int_from(expr, int_from)

        # Check if this is a static method call: StructName.method(args) (use
        # namespace). Design 144: dispatch on the identity the typechecker
        # resolved the receiver name to — the method symbols are mangled
        # against it, and two modules may each declare a `Manifest`.
        if isinstance(expr.object, Identifier):
            struct_name = (expr.resolved_type_identity
                           or expr.object.name)
            if self.namespace.is_static_method(struct_name, expr.method_name):
                return self._generate_static_method_call(expr, struct_name)

        # Check if typechecker resolved this as an enum init (e.g., lib.Color.Custom(...))
        if expr.resolved_enum_init is not None:
            return self._generate_enum_init(expr.resolved_enum_init)

        # Check if this is actually an enum initialization
        # Check both concrete enums and generic enums
        if isinstance(expr.object, Identifier):
            # Design 144: the identity the typechecker resolved, not the spelling.
            _eid = (expr.resolved_type_identity
                    or expr.object.name)
            is_enum = _eid in self.enum_types
            is_generic_enum = _eid in self.generic_enums
            if is_enum or is_generic_enum:
                # Convert to EnumInit and generate it
                enum_init = EnumInit(
                    enum_name=_eid,
                    variant_name=expr.method_name,
                    arguments=expr.arguments,
                    type_args=expr.object.type_args,  # Pass type_args for generic enums
                    line=expr.line,
                    column=expr.column
                )
                return self._generate_enum_init(enum_init)

        # Otherwise, it's a method call
        # Get mangled method name first to check if method expects mutable self
        # We need this info before generating the object expression
        # First, determine struct type by generating the object
        if receiver_ptr is not None:
            # Optional-chain method hop: the receiver is the unwrapped payload,
            # already addressed in place. Load its value for struct-type detection;
            # a `&self`/`&var self` method takes the pointer directly (below).
            obj_val = self.builder.load(receiver_ptr, name="chain_recv")
        else:
            obj_val = self._generate_expression(expr.object)

        # Determine the struct type
        # For identified types, we can get the name directly
        struct_name = None
        obj_type = obj_val.type
        if hasattr(obj_type, 'name') and obj_type.name in self.struct_types:
            # Identified type - name is directly available
            struct_name = obj_type.name
        else:
            # Fallback to string comparison for literal types
            for name, (llvm_type, _) in self.struct_types.items():
                if str(obj_type) == str(llvm_type):
                    struct_name = name
                    break

        # Check for primitive type extensions (design 57). The LLVM type of an
        # Int (i64) is ambiguous with Int64/UInt, so use the typechecker's stamped
        # SawType (`recv_saw`) to name the primitive pseudo-struct precisely;
        # fall back to the i8* shape for String. Inside a monomorphized generic
        # body the stamped type is still the abstract param `T`, so resolve it
        # through the active substitution first — a `T: Fooable` bound satisfied
        # by `extension Int: Fooable` names the `Int` pseudo-struct here (design 109).
        if struct_name is None:
            recv_saw_conc = recv_saw
            if recv_saw_conc is not None and self.type_param_context:
                recv_saw_conc = recv_saw_conc.substitute(self.type_param_context)
            prim_name = (self._primitive_ext_name(recv_saw_conc)
                         if recv_saw_conc is not None else None)
            if prim_name is not None:
                struct_name = prim_name
            elif recv_saw_conc is not None and self._canonicalize_type_kind(
                    recv_saw_conc).kind == TypeKind.ENUM:
                # Design 145: an enum receiver must be named from the stamped
                # SawType for the same reason Int is — a payload-free enum's
                # LLVM type is a bare i32, indistinguishable from Int32. Use the
                # mangled name so a generic enum's instantiation
                # (`Maybe$1$Int`) matches the symbol its methods were declared
                # under. Canonicalize first: a bare type name parses
                # STRUCT-kinded, and a reference parameter (`l: &Level`) can
                # still carry that tag for what is really an enum (design 61).
                struct_name = mangle_type(self._canonicalize_type_kind(recv_saw_conc))
            elif isinstance(obj_type, ir.PointerType):
                pointee = obj_type.pointee
                if isinstance(pointee, ir.IntType) and pointee.width == 8:
                    struct_name = "String"

        # Reference receiver (`&T` / `&var T` parameter, e.g. Set algebra's
        # `other: &Set<...>`): _generate_expression yields a POINTER to the
        # struct, so the checks above (which key on an identified struct VALUE
        # type) leave struct_name None. Recover it from the pointee so dispatch
        # and mangling work. A by-value (`&self`) method then needs the receiver
        # loaded, handled at the self_arg step below.
        if struct_name is None and isinstance(obj_type, ir.PointerType):
            pointee = obj_type.pointee
            if hasattr(pointee, 'name') and pointee.name in self.struct_types:
                struct_name = pointee.name
            else:
                for name, (llvm_type, _) in self.struct_types.items():
                    if str(pointee) == str(llvm_type):
                        struct_name = name
                        break

        # Array `.copy()` (design 33): a fixed array copies per element in index
        # order. `[trivial; N]` is a bitwise copy of the whole value; an array of
        # ExplicitCopy/ImplicitCopy elements calls each element's copy(). The
        # receiver has no struct_name (it is an LLVM `[N x T]`), so intercept here
        # before the struct-copy path.
        if expr.method_name == "copy" and len(expr.arguments) == 0:
            recv_type = self._expr_type(expr.object)
            if recv_type is not None and recv_type.kind == TypeKind.ARRAY:
                return self._emit_array_deep_copy(obj_val, recv_type)
            # `Optional<T>.copy()` (design 139) — same reason to intercept here:
            # the receiver is an LLVM `{i1, T}` with no struct_name for the
            # copy-method dispatch below to mangle.
            if recv_type is not None and recv_type.kind == TypeKind.OPTIONAL:
                return self._emit_optional_deep_copy(obj_val, recv_type)
            # `.copy()` on a TUPLE — intercepted for the same reason: the
            # receiver is an anonymous LLVM struct with no struct_name, so the
            # dispatch below would find no copy() and fall through to the
            # bitwise "auto-Copy" return, aliasing every owned element while the
            # tuple's drop glue released it twice (DF-151i).
            if recv_type is not None and recv_type.kind == TypeKind.TUPLE:
                return self._emit_tuple_deep_copy(obj_val, recv_type)
            # A declared copying policy on an ENUM derives a payload-deep copy
            # (design 139). Enums carry no method symbols, so it is emitted
            # inline here rather than dispatched to.
            if (recv_type is not None and recv_type.kind == TypeKind.ENUM
                    and recv_type.enum_name
                    and self.namespace.declared_copy_tier(recv_type.enum_name)
                    in ('implicit', 'explicit')):
                return self._emit_enum_deep_copy(obj_val, recv_type)

        # Auto-Copy: `.copy()` on a trivially-copyable receiver (a primitive, or
        # a POD struct with no copy() method) lowers to a bitwise copy, i.e. the
        # value itself. Types with a real copy() method fall through to dispatch.
        # A receiver that owns a resource (NoCopy / Deinit) but has no copy() is
        # not Copy: this is where a Vector<File>.copy() monomorphization fails,
        # with a diagnostic naming the offending element type.
        if expr.method_name == "copy" and len(expr.arguments) == 0:
            copy_mangled = self._mangle_method_name(struct_name, "copy") if struct_name else None
            if copy_mangled is None or copy_mangled not in self.functions:
                # An escaping closure is ImplicitCopy (design 73): `.copy()` bumps
                # the env refcount so the duplicate and the original each release
                # exactly once (design 77 item 3). This is the element-copy path
                # `Vector<() -> Int>.copy()` reaches via `buf[i].copy()`; without
                # the retain the shared env is freed twice (exit 133). The value
                # bytes are unchanged (the env pointer is aliased) — only the
                # atomic increment, null-env guarded inside the retain helper.
                recv_saw_copy = self._expr_type(expr.object)
                if (recv_saw_copy is not None
                        and recv_saw_copy.kind == TypeKind.FUNCTION
                        and isinstance(obj_val.type, ir.LiteralStructType)
                        and len(obj_val.type.elements) == 3):
                    env_ptr = self.builder.extract_value(obj_val, 1, name="copy_env")
                    dtor_ptr = self.builder.extract_value(obj_val, 2, name="copy_dtor")
                    self._emit_closure_env_retain(env_ptr, dtor_ptr)
                    return obj_val
                if struct_name is not None:
                    conformances = self.namespace.get_conformances(struct_name)
                    if (self.namespace.names_copy_tier(conformances)
                            or any(c in ("NoCopy", "ExplicitCopy", "Deinit")
                                   for c in conformances)):
                        raise ValueError(
                            f"cannot copy value of type `{struct_name}`: it is not Copy "
                            f"(owns a resource and has no copy()); use a copyable element "
                            f"type or implement Copy/ExplicitCopy"
                        )
                return obj_val

        # Hashable `.hash(&h)` (design 48): the single lowering point for the
        # streaming hash. A receiver with a real `hash` method (String, or a
        # struct with a synthesized/custom hash) calls it; a primitive, a
        # payload-free enum, or a trivially-copyable auto-conforming struct is
        # emitted inline via `_emit_hash`. Either way the receiver value is first
        # derefed to its value LLVM type, so a `&K`/`&String` reference receiver
        # (e.g. HashMap's `key: &K`) is handled uniformly.
        if expr.method_name == "hash" and len(expr.arguments) == 1:
            recv_type = expr.object.resolved_type
            if recv_type is not None and self.type_param_context:
                recv_type = recv_type.substitute(self.type_param_context)
            hash_val = obj_val
            if recv_type is not None:
                expected = self._get_llvm_type(recv_type)
                while (hash_val.type != expected
                       and isinstance(hash_val.type, ir.PointerType)):
                    hash_val = self.builder.load(hash_val, name="hash_recv_deref")
            hasher_ptr = self._generate_expression(expr.arguments[0].value)
            base = self._type_method_base(recv_type) if recv_type is not None else None
            mangled = self._mangle_method_name(base, "hash") if base else None
            if mangled is not None and mangled in self.functions:
                self.builder.call(self.functions[mangled], [hash_val, hasher_ptr])
            else:
                self._emit_hash(hash_val, recv_type, hasher_ptr)
            return ir.Constant(ir.IntType(32), 0)

        # Printable `.to_string()` / `.format(into:)` (design 56). A receiver with
        # a real method (a Printable user struct) dispatches normally; a builtin
        # (primitive / String) receiver is rendered inline. The typechecker only
        # marked builtin receivers as handled, so if there is no real method here
        # the receiver is a builtin and we emit inline.
        if expr.method_name in ("to_string", "format"):
            recv_type = self._expr_type(expr.object)
            if recv_type is not None and self.type_param_context:
                recv_type = recv_type.substitute(self.type_param_context)
            # Erased receiver (`&any Printable` / `Box<any Error>`): dispatch
            # through the vtable slot (design 56 x 51). A synthesized to_string
            # call (from interpolation/print) has no stamped existential_dispatch,
            # so detect it here.
            erased_trait = self._existential_receiver_info(recv_type)
            if erased_trait is not None:
                return self._generate_existential_method_call(expr, erased_trait)
            base = self._type_method_base(recv_type) if recv_type is not None else None
            mangled = self._mangle_method_name(base, expr.method_name) if base else None
            if mangled is None or mangled not in self.functions:
                # Bring a reference receiver to its value type.
                val = obj_val
                if recv_type is not None:
                    expected = self._get_llvm_type(recv_type)
                    while (val.type != expected
                           and isinstance(val.type, ir.PointerType)
                           and not (isinstance(expected, ir.PointerType))):
                        val = self.builder.load(val, name="fmt_recv_deref")
                if expr.method_name == "to_string":
                    return self._emit_to_string(val, recv_type)
                sb_ptr = self._generate_expression(expr.arguments[0].value)
                self._emit_format(val, recv_type, sb_ptr)
                return None

        if struct_name is None:
            raise ValueError(f"Cannot determine struct type for method call to {expr.method_name}")

        # Method-level generic type parameters (brief 36): a call `v.map<U>(...)`
        # carries explicit method type args. They are only known here, at the
        # call site, so the method is specialized on demand per (struct args,
        # method args) pair. Substitute the args against the active
        # monomorphization context first (the call may itself be inside another
        # generic body), then ensure the specialization exists and compose the
        # symbol so it matches the declared/queued signature.
        method_type_args = None
        if expr.type_args:
            method_type_args = [self._substitute_saw_type(a, self.type_param_context)
                                for a in expr.type_args]
            recv_type = self._expr_type(expr.object)
            # The RECEIVER's own type args need the same substitution. Inside
            # `Vector<T, A>.each`, `self.get(i)` has receiver type `Vector<T, A>`
            # as written; monomorphizing against that binds the accessor's `T` to
            # itself, and every type mentioning `T` in its signature then reaches
            # `_get_llvm_type` unsubstituted. Design 146 unit C is the first
            # caller to hit it — a std generic body calling a method-generic
            # method on its own generic receiver — because that is what a place
            # use inside std compiles to.
            if recv_type is not None and self.type_param_context:
                recv_type = self._substitute_saw_type(recv_type,
                                                      self.type_param_context)
            self._ensure_monomorphized_generic_method(
                struct_name, recv_type, expr.method_name, method_type_args)

        # Get mangled method name. Overloading (design 55): the typechecker
        # resolved the overload and stamped the exact codegen symbol; use it.
        resolved_symbol = expr.resolved_symbol
        if resolved_symbol is not None:
            mangled_name = resolved_symbol
        else:
            mangled_name = self._mangle_method_name(struct_name, expr.method_name,
                                                    method_type_args=method_type_args)

        if mangled_name not in self.functions and resolved_symbol is not None:
            # The stamped symbol names the overload against the GENERIC type
            # (`Holder_take$OL$String`); this receiver is a monomorphization, so
            # the definition lives under the specialized base. Recompose it the
            # same way `_declare_monomorphized_method` did.
            specialized = self._compose_overload_suffix(
                self._mangle_method_name(struct_name, expr.method_name,
                                         method_type_args=method_type_args),
                _StampedSymbol(resolved_symbol))
            if specialized in self.functions:
                mangled_name = specialized

        # Look up the method function
        if mangled_name not in self.functions:
            raise ValueError(f"Undefined method: {struct_name}.{expr.method_name}")

        method_func = self.functions[mangled_name]

        # Statement-scoped temporary receiver (item 4): when the receiver is a
        # freshly-produced owned value (a call/constructor result) of a
        # Deinit-needing type, nobody else owns it -- it is not bound, returned,
        # or transferred onward. Spill it to a slot and register it for LIFO
        # release at the end of the enclosing statement, so e.g.
        # `makeResource().use()` destroys the temporary after the call. An lvalue
        # receiver (Identifier / self / field) is owned by its binding and is
        # NOT registered here, which would double-free it.
        receiver_temp_slot = None
        if receiver_ptr is None and self._is_owned_temporary(expr.object):
            receiver_type = self._expr_type(expr.object)
            receiver_temp_slot = self._register_stmt_temp(obj_val, receiver_type)

        # Generate arguments: [self, arg1, arg2, ...]
        # Check if method expects mutable self (pointer to the value)
        # For String: immutable self is i8*, mutable self is i8**
        # For structs: immutable self is struct, mutable self is struct*
        self_arg = obj_val
        is_mutable_self = False
        if method_func.args:
            first_arg_type = method_func.args[0].type
            if struct_name == "String":
                # String is already i8*, so mutable self is i8** (pointer to pointer)
                if isinstance(first_arg_type, ir.PointerType):
                    pointee = first_arg_type.pointee
                    if isinstance(pointee, ir.PointerType):
                        is_mutable_self = True
            else:
                # Struct: mutable self is pointer to struct
                if isinstance(first_arg_type, ir.PointerType):
                    is_mutable_self = True

        if is_mutable_self:
            # Method expects pointer to self
            if receiver_ptr is not None:
                # Optional-chain hop: the payload is already addressed in place;
                # a `&var self` mutation lands on the real chain storage.
                self_arg = receiver_ptr
            # If object is a variable, pass its alloca directly
            elif isinstance(expr.object, Identifier) and expr.object.name in self.variables:
                self_arg = self.variables[expr.object.name]
                # If the receiver binding is itself a `&`/`&var` reference (e.g. a
                # reference parameter like `h: &var Hasher`), its alloca holds a
                # pointer TO the referent; load once so a `&var self` method gets
                # the referent's pointer, not a pointer-to-pointer (design 48:
                # `h.write_int(...)` inside `String.hash`).
                vtype = self.variable_types.get(expr.object.name)
                if vtype is not None and vtype.kind == TypeKind.REFERENCE:
                    self_arg = self.builder.load(self_arg, name="ref_self_deref")
            elif (isinstance(expr.object, Identifier)
                    and self._static_global(expr.object) is not None):
                # A module static as the receiver of a by-pointer method: the
                # global IS the storage (design 149). Falling through to the
                # spill-a-temporary branch below would lock, CAS or mutate a copy
                # of the static and throw the result away — which is what a
                # `static LOCK: SpinLock<T>` would have done.
                self_arg = self._static_global(expr.object)
            elif isinstance(expr.object, SelfExpr) and "self" in self.variables:
                # For 'self.method()' in a var self method, pass self's pointer directly
                self_ptr = self.variables["self"]
                # If self is already a pointer (var self method), use it directly
                if isinstance(self_ptr.type, ir.PointerType):
                    self_arg = self_ptr
                else:
                    self_arg = self_ptr  # It's an alloca, pass it
            elif isinstance(expr.object, MemberAccess):
                # Handle nested mutable access like self.keys.push(...)
                # We need a pointer to the field, not a copy
                self_arg = self._get_member_pointer(expr.object)
            elif isinstance(expr.object, ArrayIndex):
                # A pointer/array-element receiver — `ptr[i].mutating()` (design
                # 52b: `__group[0].__enqueue(...)`). Address the real element slot
                # so the mutation lands on the pointee, not a materialized copy.
                self_arg = self._get_element_pointer(expr.object)
            elif isinstance(expr.object, TupleIndex):
                # A TUPLE-ELEMENT receiver — `t.0.push(x)` (DF-151j). The tuple
                # projection is a place on the write side exactly as a struct
                # field is, so address the element slot; otherwise this fell to
                # the materialize-a-temporary `else` below and every mutation
                # through a tuple element was silently discarded.
                self_arg = self._get_tuple_element_pointer(expr.object)
            elif isinstance(expr.object, ForceUnwrap):
                # A `&var self` method on an opt-encoded lvalue `x!` — most
                # commonly a coroutine frame-local `self.acc!` (design 62: an
                # owning across-suspend local is opt-encoded, and `_rewrite_node`
                # turns a bare `acc` receiver into `self.acc!`). Address the
                # optional's payload IN PLACE (design 84 `&(opt!)`) so the mutation
                # lands on the real frame slot and SURVIVES the suspend. Without
                # this the receiver fell through to the materialize-a-temporary
                # `else` below, mutating a discarded copy — every `req.append(...)`
                # / `acc.push(...)` across a park was silently lost (design 86).
                self_arg = self._generate_reference_expr(
                    ReferenceExpr(expr=expr.object, mutable=True,
                                  line=expr.object.line,
                                  column=expr.object.column))
            elif receiver_temp_slot is not None:
                # An owned-temporary receiver already spilled to a slot for
                # statement-scoped cleanup: mutate through that same slot so the
                # method's effects and the end-of-statement deinit agree.
                self_arg = receiver_temp_slot
            else:
                # Otherwise create a temporary
                self_alloca = self._entry_alloca(obj_val.type, name="self_temp")
                self.builder.store(obj_val, self_alloca)
                self_arg = self_alloca

        # Reference receiver to a by-value (`&self`) method: `self_arg` is a
        # pointer to the struct (from a `&T` parameter), but an immutable-self
        # method takes the struct by value. Deref once so the LLVM types match.
        # (A normal local receiver is already a struct value, so `self_arg` is
        # not a pointer and this is skipped; a `&var self` method's first arg IS
        # a pointer, so this is skipped there too.)
        if (not is_mutable_self and method_func.args
                and not isinstance(method_func.args[0].type, ir.PointerType)
                and isinstance(self_arg.type, ir.PointerType)):
            self_arg = self.builder.load(self_arg, name="ref_recv_deref")

        args = [self_arg]  # self is first argument
        if expr.arg_plan is not None:
            # Design 66: labeled/mid-skip call — build the non-self args by the
            # binding plan. `method_defaults` includes self at index 0, so the
            # logical (self-stripped) default list is `defaults[1:]`.
            method_defs = self.method_defaults.get(mangled_name) or []
            logical_defs = method_defs[1:] if method_defs else []
            args.extend(self._planned_arg_values(
                expr, logical_defs, self._generate_expression))
        else:
            # Arguments are Argument objects with .value
            for arg in expr.arguments:
                args.append(self._gen_transfer_value(arg.value))

            # Fill in default values for missing arguments
            if mangled_name in self.method_defaults:
                defaults = self.method_defaults[mangled_name]
                # defaults includes self, so adjust index: args[0] is self, defaults[0] is self
                for i in range(len(args), len(defaults)):
                    if defaults[i] is not None:
                        args.append(self._generate_expression(defaults[i]))

        # Call the method
        mresult = self.builder.call(method_func, self._coerce_call_args(method_func, args), name="methodcall")
        if self._terminate_after_noreturn(method_func):
            return None
        return mresult

    def _interior_cell_pointer(self, obj_expr, want_pointee=None):
        """`cell.ptr()` — the address of an interior cell's own storage (186).

        The cell is layout-transparent, so its storage IS a `T` and the
        receiver's address is the answer with no field GEP on top. Shares
        `_receiver_storage_pointer` with the Atomic ops because both need the
        same thing and for the same reason: interior mutability is mutation
        through a SHARED borrow, so the address has to be the caller's storage
        rather than a copy the callee spilled.
        """
        return self._receiver_storage_pointer(obj_expr, "cell", want_pointee)

    def _atomic_cell_pointer(self, obj_expr):
        """Return an `i64*` pointing at an Atomic receiver's cell (its `value`
        field), for in-place atomic ops. The receiver must be an lvalue — a
        static, a local/self binding, or a struct field — which is exactly how
        atomics are used; a temporary receiver is spilled to a slot (its atomicity
        is then vacuous, but the code stays total)."""
        struct_ptr = self._receiver_storage_pointer(obj_expr, "atomic")
        zero = ir.Constant(ir.IntType(32), 0)
        return self.builder.gep(struct_ptr, [zero, zero], inbounds=True,
                                name="atomic_cell")

    def _receiver_storage_pointer(self, obj_expr, what: str, want_pointee=None):
        """A pointer to the receiver's OWN storage, never to a copy of it.

        `want_pointee` is the LLVM type the storage is known to hold. It matters
        only for the `&var self` deref below: a cell over a POINTER payload
        (`Once<UnsafePointer<UInt8>>`) is itself pointer-to-pointer storage, so
        the shape test alone would strip a level that is part of the value.
        """
        if isinstance(obj_expr, Identifier):
            if obj_expr.name in self.variables:
                struct_ptr = self.variables[obj_expr.name]
            elif self._static_global(obj_expr) is not None:
                struct_ptr = self._static_global(obj_expr)
            else:
                raise ValueError(f"Undefined {what} receiver: {obj_expr.name}")
        elif isinstance(obj_expr, SelfExpr):
            struct_ptr = self.variables["self"]
        elif isinstance(obj_expr, MemberAccess):
            struct_ptr = self._get_member_pointer(obj_expr)
        elif isinstance(obj_expr, TupleIndex):
            # An `Atomic` held in a tuple element (`counters.0.fetch_add(1)`):
            # the cell has to be the real one, not a spilled copy (DF-151j).
            struct_ptr = self._get_tuple_element_pointer(obj_expr)
        else:
            val = self._generate_expression(obj_expr)
            struct_ptr = self._entry_alloca(val.type, name=f"{what}_tmp")
            self.builder.store(val, struct_ptr)
        # self.variables may hold a pointer-to-pointer for a `&var self` receiver;
        # deref one level if the pointee is itself a pointer to the struct.
        if (isinstance(struct_ptr.type.pointee, ir.PointerType)
                and (want_pointee is None
                     or struct_ptr.type.pointee != want_pointee)):
            struct_ptr = self.builder.load(struct_ptr, name=f"{what}_self_deref")
        return struct_ptr

    def _generate_atomic_method(self, expr: MethodCall, recv_saw):
        """Lower an Atomic<Int> method to a seq_cst LLVM atomic (design 41 item 4).

        Ordering choice: sequentially-consistent for every operation — the
        simplest correct default (Rust's `Ordering::SeqCst`), sufficient for the
        deterministic counter tests; relaxed/acq-rel refinements are future work.
        `fetch_add` returns the PREVIOUS value; `compare_exchange` returns the
        success flag.
        """
        cell = self._atomic_cell_pointer(expr.object)
        method = expr.method_name
        if method == "load":
            return self.builder.load_atomic(cell, ordering='seq_cst', align=8,
                                            name="atomic_load")
        if method == "store":
            val = self._generate_expression(expr.arguments[0].value)
            self.builder.store_atomic(val, cell, ordering='seq_cst', align=8)
            return None
        if method == "fetch_add":
            val = self._generate_expression(expr.arguments[0].value)
            return self.builder.atomic_rmw('add', cell, val, ordering='seq_cst',
                                           name="atomic_fetch_add")
        if method == "compare_exchange":
            expected = self._generate_expression(expr.arguments[0].value)
            desired = self._generate_expression(expr.arguments[1].value)
            pair = self.builder.cmpxchg(cell, expected, desired, ordering='seq_cst',
                                        name="atomic_cmpxchg")
            return self.builder.extract_value(pair, 1, name="atomic_cmpxchg_ok")
        raise ValueError(f"unknown Atomic method: {method}")

    # =====================================================================
    # UnsafeMemory<T, Use> — typed memory at a fixed address (design 46)
    # =====================================================================

    def _um_view_type(self, um_expr):
        """The viewed type `T` of a `UnsafeMemory<T, Use>`-typed expression."""
        t = um_expr.resolved_type
        if t is not None and t.type_args:
            return t.type_args[0]
        return None

    def _um_field_order(self, view_saw, view_llvm):
        """Field order for a struct view — by name, falling back to LLVM-type
        identity for monomorphized/aliased structs (mirrors _get_member_pointer)."""
        name = getattr(view_saw, 'struct_name', None)
        if name in self.struct_types:
            return self.struct_types[name][1]
        for n, (lt, order) in self.struct_types.items():
            if str(lt) == str(view_llvm):
                return order
        raise ValueError(f"UnsafeMemory projection: unknown struct view {view_saw}")

    def _generate_um_member_projection(self, expr):
        """`UM<Struct, Use>.field` -> base + offsetof(field) as an i64 address.

        Computed with an inbounds GEP through a typed pointer materialized by
        inttoptr — LLVM's own layout arithmetic, folded to a constant offset at
        O1. The aggregate is NEVER loaded (address computation only)."""
        base_addr = self._generate_expression(expr.object)  # i64 address
        view_saw = self._um_view_type(expr.object)
        view_llvm = self._get_llvm_type(view_saw)
        field_order = self._um_field_order(view_saw, view_llvm)
        field_index = field_order.index(expr.member)
        typed_ptr = self.builder.inttoptr(base_addr, view_llvm.as_pointer(),
                                          name="um_base")
        zero = ir.Constant(ir.IntType(32), 0)
        idx = ir.Constant(ir.IntType(32), field_index)
        field_ptr = self.builder.gep(typed_ptr, [zero, idx], inbounds=True,
                                     name="um_field")
        return self.builder.ptrtoint(field_ptr, self.int_type, name="um_field_addr")

    def _generate_um_index_projection(self, expr):
        """`UM<[E; N], Use>[i]` -> base + i*sizeof(E) as an i64 address (no load)."""
        base_addr = self._generate_expression(expr.array_expr)  # i64 address
        view_saw = self._um_view_type(expr.array_expr)
        view_llvm = self._get_llvm_type(view_saw)  # [N x E]
        index_val = self._generate_expression(expr.index)
        typed_ptr = self.builder.inttoptr(base_addr, view_llvm.as_pointer(),
                                          name="um_base")
        zero = ir.Constant(ir.IntType(64), 0)
        elem_ptr = self.builder.gep(typed_ptr, [zero, index_val], inbounds=True,
                                    name="um_elem")
        return self.builder.ptrtoint(elem_ptr, self.int_type, name="um_elem_addr")

    def _generate_um_method(self, expr: MethodCall):
        """Lower a `UnsafeMemory` accessor (design 46).

        Device `read()`/`write()` emit VOLATILE loads/stores (the volatile flag
        survives the O1 pipeline — the not-elided oracle); Normal emits plain
        access. `ptr()`/`len()`/`end()` are Normal region accessors.
        """
        method = expr.um_method
        base_addr = self._generate_expression(expr.object)  # i64 address
        volatile = expr.um_volatile
        i8ptr = ir.IntType(8).as_pointer()

        if method in ("read", "write"):
            scalar_llvm = self._get_llvm_type(expr.um_scalar_type)
            typed_ptr = self.builder.inttoptr(base_addr, scalar_llvm.as_pointer(),
                                              name="um_addr")
            if method == "read":
                ld = self.builder.load(typed_ptr, name="um_read")
                if volatile:
                    ld.volatile = True
                return ld
            val = self._generate_expression(expr.arguments[0].value)
            # Coerce an Int-literal value to the register width (Int -> UInt32 etc).
            if (isinstance(val.type, ir.IntType) and isinstance(scalar_llvm, ir.IntType)
                    and val.type.width != scalar_llvm.width):
                if val.type.width > scalar_llvm.width:
                    val = self.builder.trunc(val, scalar_llvm, name="um_wtrunc")
                else:
                    val = self.builder.sext(val, scalar_llvm, name="um_wsext")
            st = self.builder.store(val, typed_ptr)
            if volatile:
                st.volatile = True
            return None

        if method == "ptr":
            return self.builder.inttoptr(base_addr, i8ptr, name="um_ptr")

        if method == "len":
            view_saw = self._um_view_type(expr.object)  # [N x E]
            view_llvm = self._get_llvm_type(view_saw)
            size = self._abi_size(view_llvm)
            return ir.Constant(self.int_type, size)  # len() -> platform Int

        if method == "end":
            view_saw = self._um_view_type(expr.object)
            view_llvm = self._get_llvm_type(view_saw)
            size = self._abi_size(view_llvm)
            end_addr = self.builder.add(base_addr, ir.Constant(self.int_type, size),
                                        name="um_end_addr")
            return self.builder.inttoptr(end_addr, i8ptr, name="um_end")

        raise ValueError(f"unknown UnsafeMemory method: {method}")

    def _generate_spawn(self, expr: FunctionCall):
        """Lower `spawn { ... }` to a pthread launch (design 21 item 5, 21b).

        Builds the escaping closure (heap env via E1), allocates a task control
        block `{ pthread_t tid, i8* env, T result }`, and starts a per-spawn
        trampoline on a fresh pthread. The trampoline runs the body, stores the
        result into the block, and tears down the env on the task thread. Returns
        a `Task<T>` value wrapping the control block.
        """
        i8ptr = ir.IntType(8).as_pointer()
        i64 = ir.IntType(64)

        closure_expr = expr.arguments[0].value
        result_saw = expr.spawn_result_type or SawType(TypeKind.VOID)
        result_llvm = self._get_llvm_type(result_saw)
        # A Void spawn body has no value to carry back: LLVM forbids a `void`
        # field in the control-block struct, so the result slot becomes a 1-byte
        # placeholder (never stored, never read — Task<Void>.join yields Void).
        result_is_void = isinstance(result_llvm, ir.VoidType)
        slot_llvm = ir.IntType(8) if result_is_void else result_llvm

        # Build the closure: heap env (escapes=True was set by the typechecker),
        # plus the generated body fn and env pointer/destructor.
        self._generate_closure(closure_expr)
        # i8* env is null if the closure has no captures (design 126 R1: these
        # come from the generator's side table, not from the AST node).
        closure_fn, env_val, env_dtor = self.closure_values[closure_expr.node_id]

        # Control block: { pthread_t tid (i8*), i8* env, T result }.
        cb_ty = ir.LiteralStructType([i8ptr, i8ptr, slot_llvm])
        cb_size = self._abi_size(cb_ty)
        # `_alloc_or_panic` uses the target word type for the seam's size/align
        # (design 47: they are i32 on riscv32, so a hardcoded i64 ICEs there)
        # and panics rather than storing through the NULL a refused allocation
        # returns (design 123).
        raw = self._alloc_or_panic(cb_size, 16, "spawn",
                                   line=expr.line)
        cb = self.builder.bitcast(raw, ir.PointerType(cb_ty), name="task_cb")
        # Store the env pointer at slot 1.
        env_slot = self.builder.gep(
            cb, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)],
            name="task_env_slot")
        self.builder.store(env_val, env_slot)

        # Emit the trampoline and launch the thread.
        tramp = self._generate_spawn_trampoline(
            cb_ty, result_llvm, closure_fn, env_dtor, result_is_void)
        tid_slot = self.builder.gep(
            cb, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)],
            name="task_tid_slot")
        # design 117: __saw_rt_thread_spawn(entry, env) RETURNS the OS thread
        # handle (pthread_t word); store it into the control block's first slot
        # (byte 0), where Task.join/Task.deinit read it back. Byte-identical
        # control-block layout to the pre-117 pthread_create-writes-the-slot form.
        handle = self.builder.call(self.functions["__saw_rt_thread_spawn"],
                                   [tramp, raw], name="task_handle")
        tid_word_slot = self.builder.bitcast(
            tid_slot, self.int_type.as_pointer(), name="task_tid_word")
        self.builder.store(handle, tid_word_slot)

        # Build the Task<T> value { handle: Some(raw), joined: false }.
        task_saw = SawType(TypeKind.STRUCT, struct_name="Task", type_args=[result_saw])
        self._ensure_monomorphized_struct("Task", [result_saw])
        task_llvm = self._get_llvm_type(task_saw)
        # handle field is `UnsafePointer<Int8>?` => { i1 is_some, i8* value }.
        handle_opt_ty = task_llvm.elements[0]
        handle_opt = ir.Constant(handle_opt_ty, ir.Undefined)
        handle_opt = self.builder.insert_value(
            handle_opt, ir.Constant(ir.IntType(1), 1), 0, name="task_handle_some")
        handle_opt = self.builder.insert_value(handle_opt, raw, 1, name="task_handle_ptr")
        task_val = ir.Constant(task_llvm, ir.Undefined)
        task_val = self.builder.insert_value(task_val, handle_opt, 0, name="task_val")
        task_val = self.builder.insert_value(
            task_val, ir.Constant(ir.IntType(1), 0), 1, name="task_joined")
        return task_val

    def _generate_spawn_trampoline(self, cb_ty, result_llvm, closure_fn, env_dtor,
                                   result_is_void=False):
        """Emit the `i8*(i8*)` pthread start routine for one spawn site.

        Loads the env from the control block, runs the closure body, stores the
        result back into the block, then runs the env destructor (drop glue for
        captured values, then free) on the task thread — exactly once, after the
        body returns. Returns NULL as the pthread result (results travel via the
        control block slot, not pthread's return channel).
        """
        i8ptr = ir.IntType(8).as_pointer()
        fn_ty = self.pthread_tramp_type  # i8*(i8*)
        # design 168 unit 3 (DF-164c): one trampoline per spawn site, and the
        # spawn site's body IS `closure_fn` — whose name is now owner+position
        # derived, so this inherits that stability for free.
        name = self._synth_symbol(f"__task_tramp${closure_fn.name}")
        tramp = ir.Function(self.module, fn_ty, name=name)

        saved_builder = self.builder
        b = ir.IRBuilder(tramp.append_basic_block("entry"))
        self.builder = b
        cb = b.bitcast(tramp.args[0], ir.PointerType(cb_ty), name="cb")
        env = b.load(
            b.gep(cb, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)]),
            name="env")
        if result_is_void:
            # Void body: run it for effect, nothing to store (the slot is a
            # placeholder i8).
            b.call(closure_fn, [env], name="body_void")
        else:
            result = b.call(closure_fn, [env], name="body_result")
            b.store(result,
                    b.gep(cb, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)]))
        # The task frame owns the closure's +1 reference (design 73): releasing it
        # on the task thread is THE release — atomic decrement of the env refcount,
        # and at zero the dtor (captures teardown + block free), exactly once. The
        # spawned closure is never copied, so its refcount is 1 here; the decrement
        # reaches 0 and frees. (`env_dtor` is None for a capture-less spawn.)
        if env_dtor is not None:
            # self.builder is already `b` here; the release helper emits into it.
            self._emit_closure_env_release(env, env_dtor)
        b.ret(ir.Constant(i8ptr, None))
        self.builder = saved_builder
        return tramp

    def _generate_arc_forward_call(self, expr: MethodCall):
        """Forward an immutable `&self` method call from an `Arc<T>` to its payload
        (design 21b E2).

        The Arc control block is `{ i64 strong, i64 weak, T payload }`; the
        payload begins at byte 16. We read the block pointer out of Arc's optional
        `ptr` field, borrow the payload slot there, and call the payload's
        monomorphized `&self` method with the payload loaded by value (an
        immutable borrow — a live strong ref pins it, so the read is sound).
        """
        payload_type = expr.arc_forward_payload_type
        arc_val = self._generate_expression(expr.object)
        # Arc.ptr is `UnsafePointer<Int8>?`, laid out as { i1 is_some, i8* value }
        # inside the single-field Arc struct { {i1, i8*} }.
        ptr_opt = self.builder.extract_value(arc_val, 0, name="arc_ptr_opt")
        block = self.builder.extract_value(ptr_opt, 1, name="arc_block")
        payload_i8 = self.builder.gep(
            block, [ir.Constant(ir.IntType(64), 16)], inbounds=True, name="arc_payload_i8")
        # Make sure the payload type's methods are monomorphized and present.
        if payload_type.kind == TypeKind.STRUCT and payload_type.type_args:
            self._ensure_monomorphized_struct(payload_type.struct_name, payload_type.type_args)
        payload_llvm = self._get_llvm_type(payload_type)
        payload_ptr = self.builder.bitcast(
            payload_i8, ir.PointerType(payload_llvm), name="arc_payload_ptr")
        mangled = self._forward_target_symbol(expr, payload_type)
        method_func = self.functions[mangled]
        self_val = self._forward_self_arg(method_func, payload_ptr,
                                          "arc_payload")
        args = [self_val]
        for arg in expr.arguments:
            args.append(self._gen_transfer_value(arg.value))
        return self.builder.call(method_func, args, name="arc_forward_call")

    def _forward_self_arg(self, method_func, payload_ptr, name: str):
        """The `self` argument a wrapper forward passes: the heap payload, by
        value or by pointer, whichever the callee's signature says.

        Both wrappers used to load unconditionally, which was right for every
        payload whose `&self` arrives by value and WRONG the moment one arrives
        by pointer — a cell-carrying payload (DF-186d). `Arc<SpinLock<Int>>`
        already had that shape before design 186 and ICE'd on the arity
        mismatch; the inline `Mutex` made it the common case. Loading would
        have been worse than the ICE if it had type-checked: `lock` would have
        taken a lock in a COPY of the payload and every thread would have
        succeeded at once.

        Reading the answer off the emitted signature rather than re-deciding it
        keeps this in step with `_self_by_pointer_for` by construction.
        """
        wants = method_func.function_type.args[0]
        if isinstance(wants, ir.PointerType):
            return payload_ptr
        return self.builder.load(payload_ptr, name=name)

    def _forward_target_symbol(self, expr: MethodCall, payload_type) -> str:
        """Mangled symbol for a wrapper payload-method forward (Arc / Box).

        A METHOD-GENERIC payload method (`func pick<R>(&self, ...)`) is only
        specialized at its call site, exactly as the ordinary method path does
        it — the type args the typechecker resolved (explicit or inferred) are
        substituted against the active monomorphization context, the monomorph
        is requested, and the symbol composes those args. Without this the
        forward looked up the NON-generic name and ICE'd on a symbol the
        monomorphizer never emits (DF-123c).
        """
        base = self._type_method_base(payload_type)
        method_type_args = None
        if expr.type_args:
            method_type_args = [self._substitute_saw_type(a, self.type_param_context)
                                for a in expr.type_args]
            self._ensure_monomorphized_generic_method(
                base, payload_type, expr.method_name, method_type_args)
        return self._mangle_method_name(base, expr.method_name,
                                        method_type_args=method_type_args)

    def _generate_box_forward_call(self, expr: MethodCall):
        """Forward an immutable `&self` method call from a `Box<T, A>` to its
        payload (design 42 item 1).

        Box is `{ T* ptr }` — the field points straight at the heap `T` (no
        control-block header, unlike Arc). Extract the pointer, load the payload
        by value (an immutable borrow — the live Box owns and pins it), and call
        the payload's monomorphized `&self` method.
        """
        payload_type = expr.box_forward_payload_type
        box_val = self._generate_expression(expr.object)
        # Box's single field is `ptr: UnsafePointer<T>` -> the payload pointer.
        payload_ptr = self.builder.extract_value(box_val, 0, name="box_ptr")
        # Make sure the payload type's methods are monomorphized and present.
        if payload_type.kind == TypeKind.STRUCT and payload_type.type_args:
            self._ensure_monomorphized_struct(payload_type.struct_name, payload_type.type_args)
        mangled = self._forward_target_symbol(expr, payload_type)
        method_func = self.functions[mangled]
        self_val = self._forward_self_arg(method_func, payload_ptr,
                                          "box_payload")
        args = [self_val]
        for arg in expr.arguments:
            args.append(self._gen_transfer_value(arg.value))
        return self.builder.call(method_func, args, name="box_forward_call")

    def _generate_field_call(self, expr: MethodCall):
        """Lower a call through a function-typed struct field: `obj.field(args)`
        (design 24 item 3).

        The field holds a closure value `{ fn_ptr, env_ptr }` (the same ABI as a
        closure bound to a local). Load the field via ordinary member access,
        then invoke it exactly like an indirect closure call.
        """
        member = MemberAccess(
            object=expr.object, member=expr.method_name,
            line=expr.line, column=expr.column)
        closure_val = self._generate_expression(member)
        # design 77 item 4: an opt-encoded closure frame field is stored as
        # `{ i1 is_some, closure }`; the closure is at element 1. (No None check —
        # a live coroutine state always assigned it before calling, mirroring the
        # `self.f!` force-unwrap the typechecker resolved.)
        if expr.field_call_unwrap:
            closure_val = self.builder.extract_value(closure_val, 1, name="field_closure_opt")
        fn_ptr = self.builder.extract_value(closure_val, 0, name="field_fn_ptr")
        env_ptr = self.builder.extract_value(closure_val, 1, name="field_env_ptr")
        arg_vals = [self._gen_transfer_value(arg.value) for arg in expr.arguments]
        return self.builder.call(fn_ptr, self._coerce_call_args(fn_ptr, [env_ptr] + arg_vals), name="field_closure_call")

    def _generate_static_method_call(self, expr: MethodCall, struct_name: str):
        """Generate a static method call: StructName.method(args)"""
        # A static method on a GENERIC struct is called with explicit type args
        # (`Vector<Int>.try_with_capacity(...)`). Monomorphize the struct for
        # those args — which also queues its extension methods, including this
        # one — and mangle against the specialized name so we call the concrete
        # instantiation (`Vector_Int_try_with_capacity`) rather than the generic
        # placeholder. Non-generic calls fall through unchanged.
        type_args = getattr(expr.object, 'type_args', None)
        if type_args and struct_name in self.generic_structs:
            # Substitute against the active monomorphization context FIRST, the
            # way the constructor path (`_generate_struct_init`) always has.
            # Without it, `Holder<T>.make(...)` written inside a `Holder<T>`
            # extension monomorphized `Holder` against the type PARAMETER `T`,
            # which self-maps in `type_param_context` and sends `_get_llvm_type`
            # into unbounded recursion — reported as `maximum recursion depth
            # exceeded` and, because std is merged into every compilation unit,
            # it took every program in the suite down with it (DF-123a). The
            # constructor spelling of the same call survived precisely because it
            # substituted here.
            type_args = [self._substitute_saw_type(a, self.type_param_context)
                         for a in type_args]
            struct_name = self._ensure_monomorphized_struct(struct_name, type_args)

        # Overloading (design 55): the typechecker resolved the static overload
        # and stamped its exact codegen symbol.
        resolved_symbol = expr.resolved_symbol
        if resolved_symbol is not None:
            mangled_name = resolved_symbol
        else:
            mangled_name = self._mangle_method_name(struct_name, expr.method_name)

        if mangled_name not in self.functions:
            raise ValueError(f"Undefined static method: {struct_name}.{expr.method_name}")

        method_func = self.functions[mangled_name]

        # Generate provided arguments
        if expr.arg_plan is not None:
            # Design 66: static methods have no self, so method_defaults is the
            # logical (self-stripped) default list directly.
            logical_defs = self.method_defaults.get(mangled_name) or []
            args = self._planned_arg_values(
                expr, logical_defs, self._generate_expression)
        else:
            args = []
            for arg in expr.arguments:
                args.append(self._gen_transfer_value(arg.value))

            # Fill in default values for missing arguments
            if mangled_name in self.method_defaults:
                defaults = self.method_defaults[mangled_name]
                for i in range(len(args), len(defaults)):
                    if defaults[i] is not None:
                        args.append(self._generate_expression(defaults[i]))

        sresult = self.builder.call(method_func, self._coerce_call_args(method_func, args), name="static_methodcall")
        if self._terminate_after_noreturn(method_func):
            return None
        return sresult

    def _resolve_module_chain(self, expr: MemberAccess):
        """Resolve a chain of module accesses like Parent.Child to get the final ModuleSymbol.

        Returns the ModuleSymbol if the entire chain is modules, None otherwise.
        """
        if isinstance(expr.object, Identifier):
            # Base case: Parent.Child where Parent is a module
            if expr.object.name in self.namespace.modules:
                parent_module = self.namespace.modules[expr.object.name]
                if parent_module.namespace and expr.member in parent_module.namespace.modules:
                    return parent_module.namespace.modules[expr.member]
        elif isinstance(expr.object, MemberAccess):
            # Recursive case: GrandParent.Parent.Child
            parent_module = self._resolve_module_chain(expr.object)
            if parent_module and parent_module.namespace and expr.member in parent_module.namespace.modules:
                return parent_module.namespace.modules[expr.member]
        return None

    def _generate_module_function_call(self, expr: MethodCall):
        """Generate a module function call: ModuleName.function(args)

        Since all modules are merged, we can call the function directly.
        """
        # Overloading (design 55): the typechecker resolved the module overload
        # and stamped its exact (merged-module) codegen symbol.
        func_name = expr.resolved_symbol or expr.method_name

        if func_name not in self.functions:
            raise ValueError(f"Undefined function in module: {expr.object.name}.{expr.method_name}")

        func = self.functions[func_name]

        # Generate arguments
        if expr.arg_plan is not None:
            # Design 66: labeled module call. Module functions carry no separate
            # default table here; the plan's slots are all argument-bound.
            args = self._planned_arg_values(
                expr, self.func_defaults.get(func_name) or [])
        else:
            args = []
            for arg in expr.arguments:
                args.append(self._gen_transfer_value(arg.value))

        modresult = self.builder.call(func, self._coerce_call_args(func, args), name="module_call")
        if self._terminate_after_noreturn(func):
            return None
        return modresult

    def _generate_module_struct_init(self, expr: MethodCall):
        """Generate a module struct initialization: ModuleName.StructName(args)

        Since all modules are merged, the struct exists in the global namespace.
        """
        # Design 144: the typechecker resolved this name through the module's
        # namespace and stamped the identity; codegen never re-resolves it.
        struct_name = (expr.resolved_type_identity
                       or expr.method_name)

        # Convert MethodCall to StructInit
        struct_init = StructInit(
            struct_name=struct_name,
            field_inits=[],
            type_args=None,
            line=expr.line,
            column=expr.column
        )

        # Handle arguments
        # struct_types[name] = (llvm_type, field_order) where field_order is a list
        if struct_name in self.struct_types:
            _, field_order = self.struct_types[struct_name]

            # Map arguments to fields
            for i, arg in enumerate(expr.arguments):
                if arg.name:
                    # Named argument
                    struct_init.field_inits.append((arg.name, arg.value))
                elif i < len(field_order):
                    # Positional argument - map to field by order
                    struct_init.field_inits.append((field_order[i], arg.value))

        # design 27 item 3: carry the matched-init decision from the typechecker
        # (`_check_module_struct_init`) so a module-qualified custom init
        # dispatches to its initializer instead of a zeroed memberwise build.
        struct_init.resolved_init_params = expr.resolved_init_params

        return self._generate_struct_init(struct_init)

    def _get_lvalue_pointer(self, expr):
        """Return a pointer to the storage backing an assignable lvalue.

        Resolves variables (loading once through a `&`/`&var` reference so the
        pointer lands on the caller's value), `self`, struct fields, and
        array/pointer elements, recursing so nested forms like `a[i].inner`
        reach real storage instead of a throwaway copy. Non-lvalue expressions
        fall back to a materialized temporary (no write-back), matching the
        historical member-access fallback.
        """
        if isinstance(expr, Identifier) and expr.name in self.variables:
            base_ptr = self.variables[expr.name]
            var_type = self.variable_types.get(expr.name)
            if var_type is not None and var_type.kind == TypeKind.REFERENCE:
                base_ptr = self.builder.load(base_ptr, name=f"{expr.name}_ref")
            return base_ptr
        # Module-level static (design 41): its global IS the storage, so a field
        # or element reached through it (`S.field`, `S[i]`) addresses the real
        # static — needed so an interior-mutable field (`S.hits.fetch_add(..)`)
        # hits the global, not a copy.
        if isinstance(expr, Identifier) and self._static_global(expr) is not None:
            return self._static_global(expr)
        if isinstance(expr, SelfExpr) and "self" in self.variables:
            return self.variables["self"]
        if isinstance(expr, MemberAccess):
            return self._get_member_pointer(expr)
        if isinstance(expr, ArrayIndex):
            return self._get_element_pointer(expr)
        if isinstance(expr, TupleIndex):
            return self._get_tuple_element_pointer(expr)
        if isinstance(expr, ForceUnwrap):
            # `opt!.field = v` — a write THROUGH a force-unwrapped optional lvalue.
            # Optionals lower to `{ i1 is_some, T payload }`, so address the
            # underlying optional and GEP to the payload slot (the `&(opt!)` path,
            # None-check included). Without this the fallback below materialized a
            # throwaway copy and the store was SILENTLY DROPPED — both for a plain
            # `var o: Point? = ...; o!.x = 99` and for an opt-encoded coroutine
            # frame local (`_rewrite_node` turns a bare `p` into `self.p!`, so
            # `p.field = v` across a suspend lost the write).
            return self._generate_reference_expr(
                ReferenceExpr(expr=expr, mutable=True,
                              line=expr.line,
                              column=expr.column))
        # Fallback: materialize a temporary (won't propagate changes back).
        base_val = self._generate_expression(expr)
        base_ptr = self._entry_alloca(base_val.type, name="lvalue_temp")
        self.builder.store(base_val, base_ptr)
        return base_ptr

    def _generate_optional_take(self, expr: MethodCall):
        """Lower `o.take()` — `Optional.take(&var self) -> T?` (design 131).

        Address the receiver place, load what is there, store `None` over it, and
        return the loaded optional. The load is the caller's now: nothing is
        retained (the place gave up its reference) and nothing is released (the
        place no longer holds one), so the payload's single reference simply
        changes hands. `is_some = false` is the whole of the None state — the
        payload bytes left behind are never read again.
        """
        opt_ptr = self._get_lvalue_pointer(expr.object)
        taken = self.builder.load(opt_ptr, name="taken")
        none_val = ir.Constant(taken.type, ir.Undefined)
        none_val = self.builder.insert_value(
            none_val, ir.Constant(ir.IntType(1), 0), 0, name="take_none")
        self.builder.store(none_val, opt_ptr)
        return taken

    def _generate_optional_presence(self, expr: MethodCall):
        """Lower `o.is_some()` / `o.is_none()` (DF-218a).

        An optional is `{ i1 is_some, T }`, so the answer is field 0 and the
        payload is never addressed. Nothing is retained (no reference is
        created) and nothing is released (none was taken), which is the whole
        reason the result does not depend on the payload's copy tier.

        A receiver that is a freshly-produced owned value still owns its
        payload after the tag is read, so it is registered for statement-end
        release exactly as an ordinary method call's temporary receiver is;
        an lvalue receiver belongs to its binding and is left alone.
        """
        obj_val = self._generate_expression(expr.object)
        if self._is_owned_temporary(expr.object):
            self._register_stmt_temp(obj_val, self._expr_type(expr.object))
        tag = self.builder.extract_value(obj_val, 0, name="opt_is_some")
        if expr.optional_presence == "is_none":
            tag = self.builder.not_(tag, name="opt_is_none")
        return tag

    def _generate_array_builtin(self, expr: MethodCall):
        """Lower a fixed-array builtin (design 72 L12/M1).

        `.len()` folds to the compile-time constant length N (an `Int`). `.swap(i,
        j)` addresses the array in place through `_get_lvalue_pointer`, bounds-
        checks both dynamic indices, and swaps the two element slots by value
        (mirrors the byte-level movement of `Vector.swap`, no element copy)."""
        kind = expr.array_builtin
        if kind == "len":
            arr_type = self._expr_type(expr.object)
            n = arr_type.array_size
            return ir.Constant(self.int_type, n)
        # swap(i, j): in-place, bounds-checked.
        arr_ptr = self._get_lvalue_pointer(expr.object)
        pointee = arr_ptr.type.pointee
        count = pointee.count
        i_val = self._generate_expression(expr.arguments[0].value)
        j_val = self._generate_expression(expr.arguments[1].value)
        self._emit_array_bounds_check(i_val, count, expr.arguments[0].value)
        self._emit_array_bounds_check(j_val, count, expr.arguments[1].value)
        zero = ir.Constant(ir.IntType(64), 0)
        i_ptr = self.builder.gep(arr_ptr, [zero, i_val], name="swap_i")
        j_ptr = self.builder.gep(arr_ptr, [zero, j_val], name="swap_j")
        i_elem = self.builder.load(i_ptr, name="swap_i_val")
        j_elem = self.builder.load(j_ptr, name="swap_j_val")
        self.builder.store(j_elem, i_ptr)
        self.builder.store(i_elem, j_ptr)
        return None

    def _get_element_pointer(self, expr: ArrayIndex):
        """Return a pointer to the `arr[i]` element slot as an lvalue.

        Composes with `_get_lvalue_pointer` so the container is addressed in
        place: a fixed array `[N x T]` is a two-index GEP into its storage; a
        raw pointer slot (`UnsafePointer` buffer) is loaded then single-index
        GEP'd. This is what lets `a[i].field = x` (and nested chains) mutate the
        real array rather than a temporary copy.
        """
        container_ptr = self._get_lvalue_pointer(expr.array_expr)
        index_val = self._generate_expression(expr.index)
        pointee = container_ptr.type.pointee
        if isinstance(pointee, ir.ArrayType):
            # Dynamic bounds check (design 63 T1b) on the write lvalue `arr[i] = v`.
            self._emit_array_bounds_check(index_val, pointee.count, expr.index)
            zero = ir.Constant(ir.IntType(64), 0)
            return self.builder.gep(container_ptr, [zero, index_val], name="elem_ptr")
        if isinstance(pointee, ir.PointerType):
            base = self.builder.load(container_ptr, name="ptr_base")
            return self.builder.gep(base, [index_val], name="ptr_elem")
        raise ValueError(f"Cannot index into type for element pointer: {pointee}")

    def _tuple_slot_pointer(self, base_expr, index: int, name: str):
        """GEP to element `index` of the tuple stored at `base_expr` (DF-151j).

        A tuple lowers to an LLVM literal struct, so an element slot is the same
        two-index GEP a struct field takes; composing through
        `_get_lvalue_pointer` is what makes `t.0`, `h.pair.0` and `a[i].0` all
        address real storage. Until this existed the tuple projection was a READ
        ONLY: `t.0.push(x)` fell through to the materialize-a-temporary fallback
        and mutated a copy that died at the end of the statement — a silent
        no-op, the failure mode design 130's accessor rule exists to forbid.
        """
        base_ptr = self._get_lvalue_pointer(base_expr)
        pointee = base_ptr.type.pointee
        if not isinstance(pointee, ir.LiteralStructType) and not isinstance(
                pointee, ir.BaseStructType):
            raise ValueError(
                f"tuple element access on non-struct storage: {pointee}")
        zero = ir.Constant(ir.IntType(32), 0)
        idx = ir.Constant(ir.IntType(32), index)
        return self.builder.gep(base_ptr, [zero, idx], name=name)

    def _get_tuple_element_pointer(self, expr: TupleIndex):
        """Return a pointer to the `t.0` element slot as an lvalue."""
        return self._tuple_slot_pointer(
            expr.tuple_expr, expr.index, name=f"tuple_{expr.index}_ptr")

    def _get_member_pointer(self, expr: MemberAccess):
        """Get a pointer to a struct field for mutable access.

        For expressions like self.keys where we need to mutate keys in place,
        this returns a GEP pointer to the field rather than extracting a copy.
        The base object is resolved through `_get_lvalue_pointer`, so a field
        reached through an array element (`a[i].field`) GEPs into real storage.
        """
        # A NAMED-TUPLE field (`pair.x`) is a MemberAccess the typechecker
        # stamped with the label's position (design 63). It is a tuple slot, not
        # a struct field: resolve it by index before the `struct_types` lookup
        # below, which would either fail outright (a tuple is an anonymous
        # literal struct, so it has no entry) or — worse — string-match a user
        # struct of identical layout and GEP by ITS field order (DF-151j).
        tuple_idx = expr.tuple_field_index
        if tuple_idx is not None:
            return self._tuple_slot_pointer(
                expr.object, tuple_idx, name=f"{expr.member}_ptr")

        # Get pointer to the base object (variable/self/field/element/fallback).
        base_ptr = self._get_lvalue_pointer(expr.object)

        # Determine the struct type
        ptr_type = base_ptr.type
        if isinstance(ptr_type, ir.PointerType):
            struct_type = ptr_type.pointee
        else:
            raise ValueError(f"Expected pointer type, got {ptr_type}")

        # Find struct name
        struct_name = None
        if hasattr(struct_type, 'name') and struct_type.name in self.struct_types:
            struct_name = struct_type.name
        else:
            for name, (llvm_type, _) in self.struct_types.items():
                if str(struct_type) == str(llvm_type):
                    struct_name = name
                    break

        if struct_name is None:
            raise ValueError(f"Cannot find struct type for member access: {expr.member}")

        # Get field index
        _, field_order = self.struct_types[struct_name]
        if expr.member not in field_order:
            raise ValueError(f"Unknown field: {struct_name}.{expr.member}")
        field_index = field_order.index(expr.member)

        # GEP to get pointer to the field
        zero = ir.Constant(ir.IntType(32), 0)
        field_idx = ir.Constant(ir.IntType(32), field_index)
        return self.builder.gep(base_ptr, [zero, field_idx], name=f"{expr.member}_ptr")

    def _generate_self_expr(self, expr: SelfExpr):
        """Generate code for 'self' keyword."""
        if "self" not in self.variables:
            raise ValueError("'self' not found in current scope")

        # Load self from its alloca
        return self.builder.load(self.variables["self"], name="self")

    def _generate_enum_init(self, expr: EnumInit):
        """Generate code for enum variant initialization."""
        # Handle generic enum with type_args. Substitute the type args against
        # the active monomorphization context FIRST (mirroring struct init), so
        # e.g. `MapSlot<K, V>.Occupied(...)` inside `Map<Int, Int>` resolves to
        # `MapSlot<Int, Int>` and NOT some other live instantiation. Without this
        # the enum-init size can be taken from a sibling monomorphization (e.g.
        # `MapSlot<Int, SetMark>` when a Set and a Map coexist).
        enum_name = expr.enum_name
        if expr.type_args:
            resolved_args = expr.type_args
            if self.type_param_context:
                resolved_args = [self._substitute_saw_type(a, self.type_param_context)
                                 for a in expr.type_args]
            enum_name = self._ensure_monomorphized_enum(expr.enum_name, resolved_args)

        if enum_name not in self.enum_types:
            raise ValueError(f"Undefined enum: {enum_name}")

        llvm_enum_type, variant_tags, variant_info = self.enum_types[enum_name]
        tag_value = variant_tags[expr.variant_name]
        variant_params = variant_info[expr.variant_name]

        # Check if this is a simple enum (just i32) or enum with payload
        if isinstance(llvm_enum_type, ir.IntType):
            # Simple enum: just return the tag value. The width is the enum's
            # own — i32 normally, the declared backing for a raw-backed enum
            # (design 145 unit B2).
            return ir.Constant(llvm_enum_type, tag_value)
        else:
            # Enum with payload: { i32 tag, [N x i8] payload }
            # Create undefined struct value
            enum_val = ir.Constant(llvm_enum_type, ir.Undefined)

            # Insert tag value
            tag_const = ir.Constant(ir.IntType(32), tag_value)
            enum_val = self.builder.insert_value(enum_val, tag_const, 0, name="enum_with_tag")

            # If this variant has associated values, pack them into payload
            if variant_params:
                # Generate values for arguments
                # Arguments are Argument objects with .value and optional .name
                arg_values = []

                # Build a dict for named args, list for positional
                arg_dict = {}
                arg_list = []
                for arg in expr.arguments:
                    if arg.is_named:
                        arg_dict[arg.name] = arg.value
                    else:
                        arg_list.append(arg.value)

                # Match arguments to parameters (named takes precedence, then positional)
                for i, (param_name, param_type) in enumerate(variant_params):
                    if param_name in arg_dict:
                        arg_expr = arg_dict[param_name]
                    elif i < len(arg_list):
                        arg_expr = arg_list[i]
                    else:
                        raise ValueError(f"Missing argument for parameter {param_name}")
                    arg_val = self._gen_transfer_value(arg_expr)
                    # Coerce a bare integer literal to a fixed-width payload field's
                    # exact width (design 65 followup) — same as struct init; without
                    # it an `Int8` payload field ICE'd inserting an i64.
                    arg_val = self._coerce_int_to_field(arg_val, param_type, arg_expr)
                    arg_values.append(arg_val)

                # Create a struct for the associated values
                param_struct_type = ir.LiteralStructType([self._get_llvm_type(t) for _, t in variant_params])
                param_struct = ir.Constant(param_struct_type, ir.Undefined)
                for i, val in enumerate(arg_values):
                    param_struct = self.builder.insert_value(param_struct, val, i, name=f"param{i}")

                # Cast the param struct to bytes and store in payload.
                payload_array_type = llvm_enum_type.elements[1]  # [N x i8]

                # Allocate temporary space sized to the FULL payload `[N x i8]`
                # (the biggest variant), NOT the smaller variant struct: the byte
                # loads below read all N bytes, so a variant-sized alloca reads out
                # of bounds past the slot (design 94 — the create/extract
                # asymmetry). Alloca the full payload, store the variant struct
                # into its front through a bitcast pointer, load the whole thing.
                payload_temp = self._entry_alloca(payload_array_type, name="payload_temp", align=8)
                struct_ptr = self.builder.bitcast(payload_temp,
                                                  ir.PointerType(param_struct_type),
                                                  name="payload_struct_ptr")
                self.builder.store(param_struct, struct_ptr)

                # Load the full payload byte array back in one shot.
                payload_bytes = self.builder.load(payload_temp, name="enum_payload_bytes")

                # Insert payload into enum
                enum_val = self.builder.insert_value(enum_val, payload_bytes, 1, name="enum_with_payload")

            return enum_val

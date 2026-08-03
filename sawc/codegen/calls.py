"""
Function and method call generation for the Saw code generator.

This module provides mixin methods for generating LLVM IR code for function
calls, method calls, static method calls, and built-in functions like print
and sizeof.

Usage:
    class CodeGenerator(CallsMixin, ...):
        pass
"""

from typing import List
from llvmlite import ir
from ast_nodes import (
    FunctionCall, StructInit, Argument, SawType, TypeKind,
    MethodCall, MemberAccess, Identifier, SelfExpr, EnumInit, ArrayIndex,
    ForceUnwrap, ReferenceExpr
)


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

    def _fill_func_defaults(self, args, key):
        """Design 53: append default-value arguments for a free-function call
        that omitted trailing arguments. The default expressions are evaluated
        fresh at the call site, per call (like the method/init default path)."""
        defaults = self.func_defaults.get(key)
        if not defaults:
            return
        for i in range(len(args), len(defaults)):
            if defaults[i] is not None:
                args.append(self._gen_transfer_value(defaults[i]))

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

    def _coerce_int_llvm(self, value, target):
        """Coerce an integer `value` to the LLVM `target` IntType (design 65
        followup). A bare integer literal reaches a fixed-width slot as the
        platform word (i64); retype the constant to the target width (out-of-range
        constants are already rejected by the typechecker). A runtime integer is
        truncated / sign-extended to fit."""
        if isinstance(value, ir.Constant):
            return ir.Constant(target, value.constant)
        if value.type.width > target.width:
            return self.builder.trunc(value, target, name="arg_trunc")
        return self.builder.sext(value, target, name="arg_sext")

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

    def _coerce_ret_value(self, value):
        """Coerce an integer return value to the current function's declared
        return width (design 65 followup) — a bare literal tail/`return` in a
        fixed-width-returning function (`func g() -> Int8 { 5 }`) reaches here as
        the platform word (i64) and would fail LLVM verification."""
        if value is None:
            return value
        rt = self.builder.function.function_type.return_type
        if (isinstance(value.type, ir.IntType) and isinstance(rt, ir.IntType)
                and value.type.width != rt.width):
            return self._coerce_int_llvm(value, rt)
        return value

    def _generate_function_call(self, expr: FunctionCall):
        """Generate code for a function call.

        Handles regular functions, generic functions, closures, struct
        initialization, and built-in functions.
        """
        # design 22: `__test_suspend()` is a synthetic suspension point for the
        # effect system. It has no runtime behavior — lower it to a no-op so
        # programs that use it still compile and run.
        # design 44: `__suspend()` is the coroutine-transform state boundary. Any
        # `__suspend` reaching codegen is one OUTSIDE a driven closure (the
        # transform rewrites the driven ones before codegen), so it too is a
        # no-op here — a lone `__suspend` behaves like `__test_suspend`.
        if expr.name in ("__test_suspend", "__suspend"):
            return None

        # Atomic construction (design 41 item 4): `Atomic(<int>)` builds the
        # `{ i64 }` cell value. The typechecker tagged this call.
        if getattr(expr, 'is_atomic_construct', False):
            atomic_saw = SawType(TypeKind.STRUCT, struct_name="Atomic",
                                 type_args=[SawType(TypeKind.INT)])
            atomic_llvm = self._get_llvm_type(atomic_saw)
            val = self._generate_expression(expr.arguments[0].value)
            cell = ir.Constant(atomic_llvm, ir.Undefined)
            return self.builder.insert_value(cell, val, 0, name="atomic_new")

        # UnsafeMemory construction (design 46): the value IS the address (i64).
        if getattr(expr, 'is_unsafe_mem_construct', False):
            return self._generate_expression(expr.arguments[0].value)

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

        # Handle the compiler-internal drop intrinsic __deinit_in_place(ptr).
        # `ptr` is an UnsafePointer<T>; run drop glue for the T value it
        # addresses, in place. Used by stdlib container deinits (Vector/Map) to
        # release live elements before freeing the backing buffer. The
        # typechecker gates this to `deinit` bodies.
        if expr.name == "__deinit_in_place":
            arg = expr.arguments[0].value
            ptr_val = self._generate_expression(arg)
            ptr_type = self._expr_type(arg)
            elem_type = ptr_type.inner_type
            if elem_type is not None and self._needs_cleanup(elem_type):
                self._emit_drop_at(ptr_val, elem_type)
            return None

        # design 45 (Part 0a): __forget(optional_place) — clear an optional
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
        if expr.name in ("yield_now", "__io_park"):
            return None
        # design 76 (A4): `io_wait(fd, dir)` reached OUTSIDE a coroutine frame (the
        # transform rewrites it to register+park inside a driven/spawned body).
        # With no executor to hand back to, register the fd and block the thread in
        # the reactor until it is ready — correct blocking semantics for a
        # non-cooperative caller.
        if expr.name == "io_wait":
            fd = self._generate_expression(expr.arguments[0].value)
            direction = self._generate_expression(expr.arguments[1].value)
            # design 91: no frame here (blocking-thread path), so no wake word to
            # route to — register with a null token. The poll skips null udata and
            # simply returns when the fd is ready, giving correct blocking semantics.
            self.builder.call(self.functions["saw_reactor_register"],
                              [fd, direction, ir.Constant(self.int_type, 0)])
            self.builder.call(self.functions["saw_reactor_poll"],
                              [ir.Constant(self.int_type, -1)])
            return None
        # design 103 (A6): the blocking-extern offload intrinsics, emitted by the
        # coro transform when it lowers a `let x = slow(arg)` blocking-extern call.
        # `__blk_start(slow(arg))` resolves the extern's ir.Function (a function
        # address is not expressible in Saw), bitcasts it to an i64, evaluates the
        # single Int arg, and hands both to the offload runtime — which spawns the
        # worker thread. The other three are thin one-arg wrappers over the runtime
        # shims (done-poll / pipe fd / join+take). All non-suspending: the SUSPENSION
        # is the `io_wait` on the job's pipe the transform emits between start and take.
        if expr.name == "__blk_start":
            inner = expr.arguments[0].value          # FunctionCall to the blocking extern
            fn = self.functions[inner.name]
            fnptr = self.builder.ptrtoint(fn, self.int_type, name="blkfn")
            argv = self._generate_expression(inner.arguments[0].value)
            return self.builder.call(self.functions["saw_offload_start"],
                                     [fnptr, argv], name="blkjob")
        if expr.name in ("__blk_done", "__blk_pipe_fd", "__blk_take"):
            shim = {"__blk_done": "saw_offload_done",
                    "__blk_pipe_fd": "saw_offload_pipe_fd",
                    "__blk_take": "saw_offload_take"}[expr.name]
            job = self._generate_expression(expr.arguments[0].value)
            return self.builder.call(self.functions[shim], [job], name="blkr")
        # `__exec_sleep(ms)` is the executor's OWN (non-suspending) timer call,
        # generated into the entry executor to honour a task's sleep wake reason.
        if expr.name in ("sleep", "__exec_sleep"):
            ms = self._generate_expression(expr.arguments[0].value)
            self.builder.call(self.functions["saw_sleep_ms"], [ms])
            return None

        if expr.name == "__forget":
            place = expr.arguments[0].value
            opt_ptr = self._get_lvalue_pointer(place)
            if opt_ptr is not None:
                i32 = ir.IntType(32)
                flag_ptr = self.builder.gep(
                    opt_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)],
                    name="forget_flag_ptr")
                self.builder.store(ir.Constant(ir.IntType(1), 0), flag_ptr)
            return None

        # design 52b item 2: `__box_data(&box)` — the data word (i8*) of a
        # `Box<any T>` fat pointer, i.e. the address of the erased heap payload.
        # `_generate_expression(&box)` is a pointer to the `{ i8* data, i8* vt }`
        # value; GEP field 0 and load it.
        if expr.name == "__box_data":
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
        resolved_symbol = getattr(expr, 'resolved_symbol', None)
        if resolved_symbol is not None and resolved_symbol in self.functions:
            func = self.functions[resolved_symbol]
            if getattr(expr, 'arg_plan', None) is not None:
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
        if expr.name in self.generic_structs or expr.name in self.struct_types:
            # Convert to struct init and generate that instead. Prefer the
            # typechecker's augmented field-init list (design 53: it includes any
            # init parameters filled from their defaults), falling back to the
            # raw named arguments.
            field_inits = getattr(expr, 'resolved_field_inits', None)
            if field_inits is None:
                field_inits = [(arg.name, arg.value) for arg in expr.arguments if arg.name]
            struct_init = StructInit(
                struct_name=expr.name,
                field_inits=field_inits,
                type_args=expr.type_args,
                line=expr.line,
                column=expr.column
            )
            # Copy resolved_init_params if it was set during typechecking
            if hasattr(expr, 'resolved_init_params'):
                struct_init.resolved_init_params = expr.resolved_init_params
            return self._generate_struct_init(struct_init)

        # Check if this is a call to a generic function. Design 105: a generic
        # overload winner carries its distinct `$OL$` base in `resolved_symbol`;
        # prefer it so the RIGHT template is instantiated (the plain name may map
        # to a sibling generic overload) and its instantiations stay collision-free.
        gen_name = expr.name
        rs = getattr(expr, 'resolved_symbol', None)
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
        else:
            # Look up regular user-defined function
            if expr.name not in self.functions:
                raise ValueError(f"Undefined function: {expr.name}")
            func = self.functions[expr.name]

        # Arguments are now Argument objects with .value
        if getattr(expr, 'arg_plan', None) is not None:
            # Design 66: labeled/mid-skip call — emit args by the binding plan,
            # interleaving default-filled parameter slots.
            args = self._planned_arg_values(
                expr, self.func_defaults.get(expr.name) or [])
        else:
            args = [self._gen_transfer_value(arg.value) for arg in expr.arguments]
            # Fill omitted trailing arguments from their default expressions (design 53).
            self._fill_func_defaults(args, expr.name)
        result = self.builder.call(func, self._coerce_call_args(func, args), name="calltmp")

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
            g = ir.GlobalVariable(self.module, arr_type,
                                  name=f".rawbytes.{self.string_counter}")
            self.string_counter += 1
            g.linkage = "private"
            g.global_constant = True
            g.initializer = ir.Constant(arr_type, bytearray(encoded))
            cache[data] = g
        g = cache[data]
        zero = ir.Constant(ir.IntType(32), 0)
        ptr = self.builder.gep(g, [zero, zero], inbounds=True)
        # Length feeds the platform-width saw_write seam (design 47).
        return ptr, ir.Constant(self.int_type, len(encoded))

    def _generate_print(self, arguments: List[Argument]):
        """Generate code for the print built-in function.

        Int family / Bool / String / interpolation all lower to saw_write (the
        output seam); only Float remains printf-based (dtoa is out of scope).
        Both paths share C stdio in the hosted profile, so mixed int/float print
        output keeps its exact order and formatting.
        """
        saw_write = self.functions["saw_write"]
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
        arg_saw = getattr(arg.value, 'resolved_type', None)
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
                iw = self.int_width
                if value.type.width < iw:
                    saw_type = self._expr_type(arg.value)
                    unsigned_kinds = {TypeKind.UINT, TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64}
                    if saw_type and saw_type.kind in unsigned_kinds:
                        value = self.builder.zext(value, self.int_type, name="print_ext")
                    else:
                        value = self.builder.sext(value, self.int_type, name="print_ext")
                elif value.type.width > iw:
                    value = self.builder.trunc(value, self.int_type, name="print_trunc")
                self.builder.call(self.functions["__saw_print_int"], [value])

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

    def _emit_runtime_panic(self, segments):
        """Assemble `segments` into one contiguous buffer and abort via saw_panic.

        `segments` is a list of `(i8* ptr, word len)` byte ranges. They are
        concatenated into a freshly allocated buffer (through __saw_string_alloc,
        which routes to saw_alloc — freestanding-safe) and handed to the
        `saw_panic(msg, len)` seam in a single call, so a freestanding handler
        receives the whole message. `unreachable` terminates the block. Nothing
        is freed: control never returns.
        """
        word = self.int_type
        i8ptr = ir.IntType(8).as_pointer()
        memcpy_fn = self._libc_func("memcpy", i8ptr, [i8ptr, i8ptr, word])

        total = ir.Constant(word, 0)
        for _, seg_len in segments:
            total = self.builder.add(total, seg_len, name="panic_len")
        buf = self.builder.call(self.functions["__saw_string_alloc"],
                                [total], name="panic_buf")
        offset = ir.Constant(word, 0)
        for seg_ptr, seg_len in segments:
            dst = self.builder.gep(buf, [offset], name="panic_seg")
            self.builder.call(memcpy_fn, [dst, seg_ptr, seg_len])
            offset = self.builder.add(offset, seg_len, name="panic_off")
        self.builder.call(self.functions["saw_panic"], [buf, total])
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
        msg_val = self._generate_expression(expr.arguments[0].value)
        msg_len = self.builder.call(self.functions["__saw_string_len"], [msg_val],
                                    name="panic_msg_len")
        prefix_ptr, prefix_len = self._raw_bytes_ptr(
            self._panic_location_prefix(getattr(expr, 'line', 0)))
        nl_ptr, nl_len = self._raw_bytes_ptr("\n")
        self._emit_runtime_panic([(prefix_ptr, prefix_len),
                                  (msg_val, msg_len),
                                  (nl_ptr, nl_len)])
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
        msg_val = self._generate_expression(expr.arguments[1].value)
        msg_len = self.builder.call(self.functions["__saw_string_len"], [msg_val],
                                    name="assert_msg_len")
        prefix_ptr, prefix_len = self._raw_bytes_ptr(
            self._panic_location_prefix(getattr(expr, 'line', 0)) + "assertion failed: ")
        suffix_ptr, suffix_len = self._raw_bytes_ptr("\n")
        self._emit_runtime_panic([(prefix_ptr, prefix_len),
                                  (msg_val, msg_len),
                                  (suffix_ptr, suffix_len)])

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
        size = 0 if isinstance(llvm_type, ir.VoidType) else llvm_type.get_abi_size(self.target_data)
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
        align = llvm_type.get_abi_alignment(self.target_data)
        return ir.Constant(self.int_type, align)  # alignof<T>() -> platform Int

    def _generate_method_call(self, expr: MethodCall):
        """Generate code for method call, static method call, enum initialization, or module function call.

        The parser creates MethodCall for all these cases:
        - object.method(args) - instance method call
        - StructName.method(args) - static method call
        - EnumType.Variant(args) - enum variant initialization
        - ModuleName.function(args) - module function call (Phase 2)
        """
        # design 51: erased-direct `Box<any Trait>.make(v)` construction, and
        # dynamic dispatch through a `&any Trait` / `Box<any Trait>` receiver. Both
        # are tagged by the typechecker.
        if getattr(expr, 'erased_box_make', None) is not None:
            return self._generate_erased_box_make(expr)
        if getattr(expr, 'existential_dispatch', None) is not None:
            return self._generate_existential_method_call(expr, expr.existential_dispatch)

        # Fixed-array builtins (design 72 L12/M1): the typechecker tagged the node.
        if getattr(expr, 'array_builtin', None) is not None:
            return self._generate_array_builtin(expr)

        # Erased-box downcasting `b.is<T>()` / `b.take<T>()` (design 72). `take`
        # consumes the box: clear the receiver binding's drop flag (like a move)
        # so scope-exit teardown does not double-free the shell take already freed.
        if getattr(expr, 'erased_downcast', None) is not None:
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
        if getattr(expr, 'arc_forward_payload_type', None) is not None:
            return self._generate_arc_forward_call(expr)

        # Box payload-method forwarding (design 42 item 1): the typechecker
        # resolved this as an immutable `&self` method on Box's payload; forward
        # through a borrow of the heap payload at `ptr[0]`.
        if getattr(expr, 'box_forward_payload_type', None) is not None:
            return self._generate_box_forward_call(expr)

        # A call through a function-typed struct field (design 24 item 3): the
        # typechecker resolved `obj.field(args)` as an indirect closure call.
        if getattr(expr, 'is_field_call', False):
            return self._generate_field_call(expr)

        # Atomic<Int> methods (design 41 item 4): lowered directly to seq_cst
        # LLVM atomics on the cell, bypassing the (dead) stub method bodies.
        # Interior mutability is the sanctioned mutation path — this fires on a
        # METHOD call, never touching the item-2 no-assignment rule.
        recv_saw = getattr(expr.object, 'resolved_type', None)
        if (recv_saw is not None and recv_saw.kind == TypeKind.STRUCT
                and recv_saw.struct_name == "Atomic"
                and expr.method_name in ("load", "store", "fetch_add", "compare_exchange")):
            return self._generate_atomic_method(expr, recv_saw)

        # UnsafeMemory accessors (design 46): read/write (volatile on Device) and
        # the Normal region accessors ptr/len/end. The typechecker tagged the node.
        if getattr(expr, 'um_method', None) is not None:
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
        if isinstance(expr.object, Identifier):
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

        # Check if this is a static method call: StructName.method(args) (use namespace)
        if isinstance(expr.object, Identifier):
            struct_name = expr.object.name
            if self.namespace.is_static_method(struct_name, expr.method_name):
                return self._generate_static_method_call(expr, struct_name)

        # Check if typechecker resolved this as an enum init (e.g., lib.Color.Custom(...))
        if hasattr(expr, 'resolved_enum_init'):
            return self._generate_enum_init(expr.resolved_enum_init)

        # Check if this is actually an enum initialization
        # Check both concrete enums and generic enums
        if isinstance(expr.object, Identifier):
            is_enum = expr.object.name in self.enum_types
            is_generic_enum = expr.object.name in self.generic_enums
            if is_enum or is_generic_enum:
                # Convert to EnumInit and generate it
                enum_init = EnumInit(
                    enum_name=expr.object.name,
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
        # fall back to the i8* shape for String.
        if struct_name is None:
            if recv_saw is not None and recv_saw.kind == TypeKind.INT:
                struct_name = "Int"
            elif recv_saw is not None and recv_saw.kind == TypeKind.FLOAT:
                struct_name = "Float"
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
                    if any(c in ("NoCopy", "ImplicitCopy", "ExplicitCopy", "Deinit")
                           for c in conformances):
                        raise ValueError(
                            f"cannot copy value of type `{struct_name}`: it is not Copy "
                            f"(owns a resource and has no copy()); use a copyable element "
                            f"type or implement ImplicitCopy/ExplicitCopy"
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
            recv_type = getattr(expr.object, 'resolved_type', None)
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
            self._ensure_monomorphized_generic_method(
                struct_name, recv_type, expr.method_name, method_type_args)

        # Get mangled method name. Overloading (design 55): the typechecker
        # resolved the overload and stamped the exact codegen symbol; use it.
        resolved_symbol = getattr(expr, 'resolved_symbol', None)
        if resolved_symbol is not None:
            mangled_name = resolved_symbol
        else:
            mangled_name = self._mangle_method_name(struct_name, expr.method_name,
                                                    method_type_args=method_type_args)

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
        if self._is_owned_temporary(expr.object):
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
            # If object is a variable, pass its alloca directly
            if isinstance(expr.object, Identifier) and expr.object.name in self.variables:
                self_arg = self.variables[expr.object.name]
                # If the receiver binding is itself a `&`/`&var` reference (e.g. a
                # reference parameter like `h: &var Hasher`), its alloca holds a
                # pointer TO the referent; load once so a `&var self` method gets
                # the referent's pointer, not a pointer-to-pointer (design 48:
                # `h.write_int(...)` inside `String.hash`).
                vtype = self.variable_types.get(expr.object.name)
                if vtype is not None and vtype.kind == TypeKind.REFERENCE:
                    self_arg = self.builder.load(self_arg, name="ref_self_deref")
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
                                  line=getattr(expr.object, 'line', 0),
                                  column=getattr(expr.object, 'column', 0)))
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
        if getattr(expr, 'arg_plan', None) is not None:
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
        return self.builder.call(method_func, self._coerce_call_args(method_func, args), name="methodcall")

    def _atomic_cell_pointer(self, obj_expr):
        """Return an `i64*` pointing at an Atomic receiver's cell (its `value`
        field), for in-place atomic ops. The receiver must be an lvalue — a
        static, a local/self binding, or a struct field — which is exactly how
        atomics are used; a temporary receiver is spilled to a slot (its atomicity
        is then vacuous, but the code stays total)."""
        if isinstance(obj_expr, Identifier):
            if obj_expr.name in self.variables:
                struct_ptr = self.variables[obj_expr.name]
            elif obj_expr.name in self.static_globals:
                struct_ptr = self.static_globals[obj_expr.name]
            else:
                raise ValueError(f"Undefined Atomic receiver: {obj_expr.name}")
        elif isinstance(obj_expr, SelfExpr):
            struct_ptr = self.variables["self"]
        elif isinstance(obj_expr, MemberAccess):
            struct_ptr = self._get_member_pointer(obj_expr)
        else:
            val = self._generate_expression(obj_expr)
            struct_ptr = self._entry_alloca(val.type, name="atomic_tmp")
            self.builder.store(val, struct_ptr)
        # self.variables may hold a pointer-to-pointer for a `&var self` receiver;
        # deref one level if the pointee is itself a pointer to the struct.
        if isinstance(struct_ptr.type.pointee, ir.PointerType):
            struct_ptr = self.builder.load(struct_ptr, name="atomic_self_deref")
        zero = ir.Constant(ir.IntType(32), 0)
        return self.builder.gep(struct_ptr, [zero, zero], inbounds=True, name="atomic_cell")

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
        t = getattr(um_expr, 'resolved_type', None)
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

    def _generate_um_method(self, expr):
        """Lower a `UnsafeMemory` accessor (design 46).

        Device `read()`/`write()` emit VOLATILE loads/stores (the volatile flag
        survives the O1 pipeline — the not-elided oracle); Normal emits plain
        access. `ptr()`/`len()`/`end()` are Normal region accessors.
        """
        method = expr.um_method
        base_addr = self._generate_expression(expr.object)  # i64 address
        volatile = bool(getattr(expr, 'um_volatile', False))
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
            size = view_llvm.get_abi_size(self.target_data)
            return ir.Constant(self.int_type, size)  # len() -> platform Int

        if method == "end":
            view_saw = self._um_view_type(expr.object)
            view_llvm = self._get_llvm_type(view_saw)
            size = view_llvm.get_abi_size(self.target_data)
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
        result_saw = getattr(expr, 'spawn_result_type', None) or SawType(TypeKind.VOID)
        result_llvm = self._get_llvm_type(result_saw)
        # A Void spawn body has no value to carry back: LLVM forbids a `void`
        # field in the control-block struct, so the result slot becomes a 1-byte
        # placeholder (never stored, never read — Task<Void>.join yields Void).
        result_is_void = isinstance(result_llvm, ir.VoidType)
        slot_llvm = ir.IntType(8) if result_is_void else result_llvm

        # Build the closure: heap env (escapes=True was set by the typechecker),
        # plus the generated body fn and env pointer/destructor.
        self._generate_closure(closure_expr)
        closure_fn = closure_expr._cg_closure_fn
        env_val = closure_expr._cg_env_value  # i8* (null if no captures)
        env_dtor = getattr(closure_expr, 'codegen_env_dtor', None)

        # Control block: { pthread_t tid (i8*), i8* env, T result }.
        cb_ty = ir.LiteralStructType([i8ptr, i8ptr, slot_llvm])
        cb_size = cb_ty.get_abi_size(self.target_data)
        raw = self.builder.call(
            self.functions["saw_alloc"],
            [ir.Constant(i64, cb_size), ir.Constant(i64, 16)], name="task_cb_raw")
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
        tid_i8 = self.builder.bitcast(tid_slot, i8ptr, name="task_tid_i8")
        self.builder.call(self.functions["__saw_pthread_create"],
                          [tid_i8, tramp, raw])

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
        name = f"__task_tramp_{self.closure_counter}"
        self.closure_counter += 1
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
        self_val = self.builder.load(payload_ptr, name="arc_payload")

        mangled = self._mangle_method_name(
            self._type_method_base(payload_type), expr.method_name)
        method_func = self.functions[mangled]
        args = [self_val]
        for arg in expr.arguments:
            args.append(self._gen_transfer_value(arg.value))
        return self.builder.call(method_func, args, name="arc_forward_call")

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
        self_val = self.builder.load(payload_ptr, name="box_payload")

        mangled = self._mangle_method_name(
            self._type_method_base(payload_type), expr.method_name)
        method_func = self.functions[mangled]
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
        if getattr(expr, 'field_call_unwrap', False):
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
            struct_name = self._ensure_monomorphized_struct(struct_name, type_args)

        # Overloading (design 55): the typechecker resolved the static overload
        # and stamped its exact codegen symbol.
        resolved_symbol = getattr(expr, 'resolved_symbol', None)
        if resolved_symbol is not None:
            mangled_name = resolved_symbol
        else:
            mangled_name = self._mangle_method_name(struct_name, expr.method_name)

        if mangled_name not in self.functions:
            raise ValueError(f"Undefined static method: {struct_name}.{expr.method_name}")

        method_func = self.functions[mangled_name]

        # Generate provided arguments
        if getattr(expr, 'arg_plan', None) is not None:
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

        return self.builder.call(method_func, self._coerce_call_args(method_func, args), name="static_methodcall")

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
        func_name = getattr(expr, 'resolved_symbol', None) or expr.method_name

        if func_name not in self.functions:
            raise ValueError(f"Undefined function in module: {expr.object.name}.{expr.method_name}")

        func = self.functions[func_name]

        # Generate arguments
        if getattr(expr, 'arg_plan', None) is not None:
            # Design 66: labeled module call. Module functions carry no separate
            # default table here; the plan's slots are all argument-bound.
            args = self._planned_arg_values(
                expr, self.func_defaults.get(func_name) or [])
        else:
            args = []
            for arg in expr.arguments:
                args.append(self._gen_transfer_value(arg.value))

        return self.builder.call(func, self._coerce_call_args(func, args), name="module_call")

    def _generate_module_struct_init(self, expr: MethodCall):
        """Generate a module struct initialization: ModuleName.StructName(args)

        Since all modules are merged, the struct exists in the global namespace.
        """
        struct_name = expr.method_name

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
        if hasattr(expr, 'resolved_init_params'):
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
        if isinstance(expr, Identifier) and expr.name in self.static_globals:
            return self.static_globals[expr.name]
        if isinstance(expr, SelfExpr) and "self" in self.variables:
            return self.variables["self"]
        if isinstance(expr, MemberAccess):
            return self._get_member_pointer(expr)
        if isinstance(expr, ArrayIndex):
            return self._get_element_pointer(expr)
        # Fallback: materialize a temporary (won't propagate changes back).
        base_val = self._generate_expression(expr)
        base_ptr = self._entry_alloca(base_val.type, name="lvalue_temp")
        self.builder.store(base_val, base_ptr)
        return base_ptr

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

    def _get_member_pointer(self, expr: MemberAccess):
        """Get a pointer to a struct field for mutable access.

        For expressions like self.keys where we need to mutate keys in place,
        this returns a GEP pointer to the field rather than extracting a copy.
        The base object is resolved through `_get_lvalue_pointer`, so a field
        reached through an array element (`a[i].field`) GEPs into real storage.
        """
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
            # Simple enum: just return the tag value
            return ir.Constant(ir.IntType(32), tag_value)
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

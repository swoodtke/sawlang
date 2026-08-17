"""
`any Trait` existential codegen (design 51).

An erased value is a FAT POINTER — a two-word `{ i8* data, i8* vtable }` value —
used identically for a borrowed `&any Trait` and an owned `Box<any Trait, A>`.
The vtable is a per-(concrete type, trait) const global laid out as

    { void(i8*)* destructor, isize size, isize align, <method thunks...> }

with the method thunks in trait declaration order. Each thunk adapts the uniform
`(i8* self, args...) -> ret` dispatch ABI to the concrete method (loading the
value for a by-value `&self` receiver, or passing the pointer for `&var self`).
Vtables/thunks/destructors are emitted lazily on first use and drained at the
end of module generation, mirroring the monomorphization pending queue.

Erasure happens only at construction/call boundaries: a `&concrete` coerced to
`&any Trait` (attaching the vtable), and erased-direct `Box<any Trait>.make(v)`.
Dispatch loads a method thunk from the vtable and calls it with the data pointer.
Box teardown pulls the destructor + size + align from the vtable (never a static
`sizeof<T>`, since the payload is erased) and routes dealloc to the box's `A`.
"""

from llvmlite import ir
from ast_nodes import SawType, TypeKind
from codegen.mangle import mangle_type, mangle_method


class ExistentialsMixin:
    """Mixed into CodeGenerator; owns `any Trait` lowering, vtables, dispatch."""

    # The vtable header is `{ dtor*, isize size, isize align, isize type_id }`;
    # method thunks follow, so the first method thunk is at this slot index.
    _VTABLE_METHOD_BASE = 4

    # ------------------------------------------------------------------ state
    def _existential_init(self):
        # (concrete_mangle, trait_name) -> vtable GlobalVariable
        self._vtable_globals = {}
        # concrete_mangle -> destructor ir.Function
        self._vtable_dtors = {}
        # (concrete_mangle, trait_name, method_name) -> thunk ir.Function
        self._vtable_thunks = {}
        # queued (concrete_saw, trait_name, global, vtable_llvm_type) to fill/drain
        self._pending_vtables = []
        # concrete_mangle -> stable per-concrete-type id (design 72 downcasting).
        # Memoized by mangled name so the id the vtable BAKES IN matches the one
        # `is<T>()`/`take<T>()` COMPUTE for the same concrete type (design 87 §2).
        self._type_ids = {}

    # FNV-1a 64-bit (the same constants as the runtime Hasher in builtin.saw).
    _FNV64_OFFSET_BASIS = 14695981039346656037
    _FNV64_PRIME = 1099511628211
    _FNV64_MASK = (1 << 64) - 1

    def _erased_identity(self, concrete_saw):
        """THE ONE canonical spelling a concrete type takes when it is ERASED.

        Four identities are derived from an erased type's mangled name — the
        vtable global, the destructor it points at, the impl symbol each method
        thunk calls, and the `type_id` a downcast compares — so all four have to
        spell the same type the same way. `_canonicalize_type_kind` is that
        spelling (design 68): it fills omitted trailing default type args at
        every nesting level and normalizes an erased `Box<any Trait, Global>`
        back down to codegen's native arity-1 form, which is what
        `_ensure_monomorphized_struct` registers the type and its methods under.

        THE FUNNEL, and its entry points (design 190 obligation 1):
        `_get_or_emit_vtable` — which covers everything `_fill_vtable` then
        derives, i.e. `_get_vtable_dtor`, `_get_vtable_thunk` and the
        size/align header — and `_type_id_for`, which is called from BOTH sides
        of a downcast (the id the vtable bakes in, and the id `is<T>()` /
        `take<T>()` compare against it). Any new way to reach a vtable belongs
        here too, or it mangles a second name for one type.

        DF-192b is what a bypass costs: spawning a function that returns an
        erased `Result<T, Box<any Error>>` monomorphized its result cell as
        `__ResultCell<Result<Int, Box<any Error>>>` and then asked for a vtable
        over the arity-2 `Box<any Error, GlobalAllocator>` spelling of the same
        type, so the thunk's impl lookup missed by a name and the compiler died
        with a bare `KeyError`.
        """
        return self._canonicalize_type_kind(concrete_saw)

    def _type_id_for(self, concrete_saw):
        """A STABLE, deterministic type-id: the FNV-1a hash of the mangled type
        name (design 87 §2, replacing design-72's per-compilation MONOTONIC
        COUNTER). Because the id is a pure function of the mangled name, the SAME
        concrete type hashes to the SAME id in EVERY compilation — so a future
        separate-compilation unit would agree on `is<T>()`/`take<T>()`, not just
        the current whole-program build. The vtable slot the id bakes into and
        the downcast compare against it both call here, so they always agree.

        Masked to the platform word so it fits the vtable's `int_type` type_id
        slot (i64 hosted, i32 on riscv32). COLLISION POSTURE: distinct mangled
        names over a 64-bit FNV space make an accidental clash negligible (a
        birthday clash needs ~2^32 conforming types in one program); ids are only
        ever compared for EQUALITY, never used as a sentinel, so `0` is a legal id
        (unlike the old counter, which reserved it). A hypothetical collision
        would let one type's `is<T>()` spuriously accept another — acceptable for
        a v1 downcast until a wider/perfect scheme is warranted."""
        cm = mangle_type(self._erased_identity(concrete_saw))
        tid = self._type_ids.get(cm)
        if tid is None:
            h = self._FNV64_OFFSET_BASIS
            for byte in cm.encode('utf-8'):
                h = ((h ^ byte) * self._FNV64_PRIME) & self._FNV64_MASK
            tid = h & ((1 << self.int_width) - 1)
            self._type_ids[cm] = tid
        return tid

    # ----------------------------------------------------------- llvm helpers
    def _i8ptr(self):
        return ir.PointerType(ir.IntType(8))

    def _existential_llvm_type(self):
        """The fat-pointer representation shared by `&any T` and `Box<any T>`."""
        return ir.LiteralStructType([self._i8ptr(), self._i8ptr()])

    def _is_erased_box(self, saw_type):
        """True for `Box<any Trait, A>` — an owned erased value (fat pointer)."""
        return (saw_type is not None and saw_type.kind == TypeKind.STRUCT
                and saw_type.struct_name == "Box" and saw_type.type_args
                and saw_type.type_args[0].kind == TypeKind.EXISTENTIAL)

    def _trait_dispatch_methods(self, trait_name):
        """Ordered [(name, TraitMethodSymbol)] — the single source of truth for
        vtable slot order, used by emission AND dispatch so they always agree."""
        trait = self.namespace.lookup_trait(trait_name)
        if trait is None:
            return []
        return list(trait.methods.items())

    def _trait_slot_fn_type(self, tmethod):
        """The uniform dispatch fn-pointer type for one trait method: the receiver
        is always `i8*` (the erased data pointer); the remaining params + return
        come from the trait signature. Identical for every concrete conformer, so
        the vtable layout is uniform per trait."""
        # param_types[0] is the VOID `self` placeholder; the rest are real params.
        arg_llvm = [self._get_llvm_type(pt)
                    for pt in (tmethod.param_types or [])[1:]]
        # design 228 leg 3: a `-> Never` requirement's slot is `void` through
        # the one funnel. Slot type and thunk type both come from here, so they
        # cannot drift apart, and the thunk's own `unreachable` comes from the
        # `noreturn` on the conformer it tail-calls.
        ret_llvm, _ = self._lower_declared_return(tmethod.return_type)
        return ir.FunctionType(ret_llvm, [self._i8ptr()] + arg_llvm)

    def _vtable_llvm_type(self, trait_name):
        """`{ dtor*, isize size, isize align, isize type_id, method0*, ... }` for a
        trait. The `type_id` header slot (design 72) backs erased downcasting."""
        fields = [ir.PointerType(ir.FunctionType(ir.VoidType(), [self._i8ptr()])),
                  self.int_type, self.int_type, self.int_type]
        for _name, tmethod in self._trait_dispatch_methods(trait_name):
            fields.append(ir.PointerType(self._trait_slot_fn_type(tmethod)))
        return ir.LiteralStructType(fields)

    # ---------------------------------------------------- vtable synthesis (3)
    def _get_or_emit_vtable(self, concrete_saw, trait_name):
        """Return the (lazily-emitted) vtable global for a (type, trait) pair.

        Emitted on first use like a monomorphization: the global is created now
        (so its address is available to build fat pointers), and its initializer
        + destructor/thunk bodies are filled during the end-of-module drain, when
        the builder context is clean and all impl functions are declared.

        The concrete type is canonicalized here, once, so the queued
        `concrete_saw` every downstream slot reads is already the erased
        identity — see `_erased_identity`."""
        concrete_saw = self._erased_identity(concrete_saw)
        cm = mangle_type(concrete_saw)
        key = (cm, trait_name)
        existing = self._vtable_globals.get(key)
        if existing is not None:
            return existing
        vt_ty = self._vtable_llvm_type(trait_name)
        g = ir.GlobalVariable(self.module, vt_ty, name=f"__vtable${cm}${trait_name}")
        g.linkage = 'private'
        g.global_constant = True
        self._vtable_globals[key] = g
        self._pending_vtables.append((concrete_saw, trait_name, g, vt_ty))
        return g

    def _emit_pending_vtables(self):
        """Drain the vtable queue. Filling a vtable can enqueue nothing new (the
        concrete types are already known), so a simple loop suffices."""
        while self._pending_vtables:
            concrete_saw, trait_name, g, vt_ty = self._pending_vtables.pop()
            self._fill_vtable(concrete_saw, trait_name, g, vt_ty)

    def _fill_vtable(self, concrete_saw, trait_name, g, vt_ty):
        saved_ctx = self.type_param_context
        self.type_param_context = {}  # concrete type: no type params in scope
        try:
            concrete_llvm = self._get_llvm_type(concrete_saw)
            size = self._abi_size(concrete_llvm)
            align = self._abi_align(concrete_llvm)
            dtor = self._get_vtable_dtor(concrete_saw)
            type_id = self._type_id_for(concrete_saw)
            elems = [dtor, ir.Constant(self.int_type, size),
                     ir.Constant(self.int_type, align),
                     ir.Constant(self.int_type, type_id)]
            for mname, tmethod in self._trait_dispatch_methods(trait_name):
                elems.append(self._get_vtable_thunk(
                    concrete_saw, trait_name, mname, tmethod))
            g.initializer = ir.Constant(vt_ty, elems)
        finally:
            self.type_param_context = saved_ctx

    def _get_vtable_dtor(self, concrete_saw):
        """A `void(i8*)` that runs the concrete type's drop glue in place (the
        vtable destructor slot). One per concrete type, shared across traits."""
        cm = mangle_type(concrete_saw)
        existing = self._vtable_dtors.get(cm)
        if existing is not None:
            return existing
        fn_ty = ir.FunctionType(ir.VoidType(), [self._i8ptr()])
        fn = ir.Function(self.module, fn_ty, name=f"__vtdtor${cm}")
        fn.linkage = 'internal'
        self._vtable_dtors[cm] = fn
        saved_builder = self.builder
        block = fn.append_basic_block("entry")
        self.builder = ir.IRBuilder(block)
        try:
            concrete_llvm = self._get_llvm_type(concrete_saw)
            typed = self.builder.bitcast(fn.args[0], concrete_llvm.as_pointer())
            if self._needs_cleanup(concrete_saw):
                self._emit_drop_at(typed, concrete_saw)
            self.builder.ret_void()
        finally:
            self.builder = saved_builder
        return fn

    def _get_vtable_thunk(self, concrete_saw, trait_name, mname, tmethod):
        """Adapt the uniform `(i8* self, args...) -> ret` ABI to the concrete
        impl: bitcast the data pointer to the concrete type, then either load the
        value (by-value `&self`) or pass the pointer (`&var self`) as the impl's
        receiver, forwarding remaining args unchanged."""
        cm = mangle_type(concrete_saw)
        key = (cm, trait_name, mname)
        existing = self._vtable_thunks.get(key)
        if existing is not None:
            return existing
        impl = self.functions[mangle_method(cm, mname)]
        thunk_ty = self._trait_slot_fn_type(tmethod)
        thunk = ir.Function(self.module, thunk_ty,
                            name=f"__vtthunk${cm}${trait_name}${mname}")
        thunk.linkage = 'internal'
        self._vtable_thunks[key] = thunk
        saved_builder = self.builder
        block = thunk.append_basic_block("entry")
        self.builder = ir.IRBuilder(block)
        try:
            concrete_llvm = self._get_llvm_type(concrete_saw)
            data_ptr = self.builder.bitcast(thunk.args[0], concrete_llvm.as_pointer())
            # Read the convention off the IMPL's own signature rather than the
            # trait requirement's spelling: `&var self` and a `borrows` accessor
            # take a pointer, and so does a plain `&self` on a receiver carrying
            # an `Atomic` cell (design 149). The emitted parameter type is the one
            # answer all three agree on.
            if isinstance(impl.args[0].type, ir.PointerType):
                self_arg = data_ptr                       # by pointer
            else:
                self_arg = self.builder.load(data_ptr)    # &self: by value
            call_args = [self_arg] + list(thunk.args[1:])
            res = self.builder.call(impl, call_args)
            if isinstance(thunk_ty.return_type, ir.VoidType):
                self.builder.ret_void()
            else:
                self.builder.ret(res)
        finally:
            self.builder = saved_builder
        return thunk

    # -------------------------------------------------- erasure coercion (4)
    def _erase_pointer_to_any(self, data_ptr, concrete_saw, trait_name):
        """Build a fat-pointer value from a pointer to a live concrete value and
        the (concrete, trait) vtable. Used for `&concrete -> &any Trait`."""
        i8 = self._i8ptr()
        vt = self._get_or_emit_vtable(concrete_saw, trait_name)
        data_i8 = self.builder.bitcast(data_ptr, i8)
        vt_i8 = self.builder.bitcast(vt, i8)
        fat = ir.Constant(self._existential_llvm_type(), ir.Undefined)
        fat = self.builder.insert_value(fat, data_i8, 0)
        fat = self.builder.insert_value(fat, vt_i8, 1)
        return fat

    # ------------------------------------------------- method dispatch (4)
    def _existential_receiver_info(self, saw_type):
        """If `saw_type` names an erased receiver, return its trait name; else
        None. Accepts `any T`, `&any T`, and `Box<any T, A>`."""
        if saw_type is None:
            return None
        if saw_type.kind == TypeKind.EXISTENTIAL:
            return saw_type.existential_trait
        if (saw_type.kind == TypeKind.REFERENCE and saw_type.inner_type is not None
                and saw_type.inner_type.kind == TypeKind.EXISTENTIAL):
            return saw_type.inner_type.existential_trait
        if (saw_type.kind == TypeKind.STRUCT and saw_type.struct_name == "Box"
                and saw_type.type_args
                and saw_type.type_args[0].kind == TypeKind.EXISTENTIAL):
            return saw_type.type_args[0].existential_trait
        return None

    def _generate_existential_method_call(self, expr, trait_name):
        """Dynamic dispatch through a fat pointer: extract (data, vtable), load
        the method thunk from its slot, and call it with the data pointer."""
        recv = self._generate_expression(expr.object)
        # The receiver value is the fat pointer { i8* data, i8* vtable }.
        data = self.builder.extract_value(recv, 0)
        vtable_i8 = self.builder.extract_value(recv, 1)

        methods = self._trait_dispatch_methods(trait_name)
        slot = None
        tmethod = None
        for idx, (mname, tm) in enumerate(methods):
            if mname == expr.method_name:
                slot = self._VTABLE_METHOD_BASE + idx  # after dtor,size,align,type_id
                tmethod = tm
                break
        if slot is None:
            raise ValueError(
                f"trait `{trait_name}` has no method `{expr.method_name}`")

        vt_ty = self._vtable_llvm_type(trait_name)
        vtable_ptr = self.builder.bitcast(vtable_i8, vt_ty.as_pointer())
        zero = ir.Constant(self.int_type, 0)
        slot_gep = self.builder.gep(
            vtable_ptr, [zero, ir.Constant(ir.IntType(32), slot)])
        fn_ptr = self.builder.load(slot_gep)

        args = [data]
        for arg in expr.arguments:
            args.append(self._gen_transfer_value(arg.value))
        # design 228 legs 2 + 5: dispatch is a call like any other — a diverging
        # ARGUMENT aborts it, and a `-> Never` requirement terminates after it.
        # The callee is a loaded fn POINTER with no attribute list, so the
        # divergence answer comes from the call expression, as it does for a
        # closure. Sound here for the same reason: design 141 admits no
        # `borrows` trait requirements, so this call's type IS the callee's
        # return type.
        result = self._emit_call(fn_ptr, args, "anydispatch", closure_call=expr,
                                 coerce=False)
        if result is None or isinstance(fn_ptr.type.pointee.return_type, ir.VoidType):
            return None
        return result

    # ------------------------------------------- erased Box construct (4) / teardown (5)
    def _generate_erased_box_make(self, expr):
        """`Box<any Trait>.make(v)` built erased-directly (design 51): allocate a
        chunk sized to the CONCRETE value through the box's `A`, placement-move the
        value in, and return the fat pointer { data, vtable }. Size/align are the
        concrete type's (statically known here); teardown later recovers them from
        the vtable. OOM panics (the infallible tier), matching `Box<T>.make`."""
        info = expr.erased_box_make
        trait_name = info['trait']
        concrete_saw = info['concrete']
        alloc_saw = info['allocator']
        # Lower the concrete payload value once (consumes/moves the argument).
        value = self._gen_transfer_value(expr.arguments[0].value)
        return self._erase_value_to_box(value, concrete_saw, trait_name, alloc_saw)

    def _erase_value_to_box(self, value, concrete_saw, trait_name, alloc_saw):
        """Box an already-lowered concrete `value` behind `trait_name` through
        `alloc_saw`, returning the fat pointer { data, vtable }. Shared by
        `Box<any T>.make(v)` and auto-erasure of a concrete error at a return /
        propagation edge (design 56). OOM panics (the infallible tier)."""
        i8 = self._i8ptr()
        concrete_llvm = self._get_llvm_type(concrete_saw)
        size = ir.Constant(self.int_type, self._abi_size(concrete_llvm))
        align = ir.Constant(self.int_type, self._abi_align(concrete_llvm))

        # Allocate through A().alloc(size, align) -> UnsafePointer<Int8>? = {i1,i8*}.
        alloc_fn = self.functions[mangle_method(mangle_type(alloc_saw), "alloc")]
        a_self = ir.Constant(self._get_llvm_type(alloc_saw), ir.Undefined)
        opt = self.builder.call(alloc_fn, [a_self, size, align], name="anyalloc")
        is_some = self.builder.extract_value(opt, 0)
        raw = self.builder.extract_value(opt, 1)  # i8* (valid only if is_some)

        vt = self._get_or_emit_vtable(concrete_saw, trait_name)
        vt_i8 = self.builder.bitcast(vt, i8)

        fat_ty = self._existential_llvm_type()
        result_slot = self.builder.alloca(fat_ty, name="anybox")

        ok_block = self.builder.append_basic_block("anybox_ok")
        fail_block = self.builder.append_basic_block("anybox_fail")
        cont_block = self.builder.append_basic_block("anybox_cont")
        self.builder.cbranch(is_some, ok_block, fail_block)

        # Success: placement-move the value into the fresh chunk, build the fat ptr.
        self.builder.position_at_end(ok_block)
        typed = self.builder.bitcast(raw, concrete_llvm.as_pointer())
        self.builder.store(value, typed)
        fat = ir.Constant(fat_ty, ir.Undefined)
        fat = self.builder.insert_value(fat, raw, 0)
        fat = self.builder.insert_value(fat, vt_i8, 1)
        self.builder.store(fat, result_slot)
        self.builder.branch(cont_block)

        # Failure: the infallible tier panics (Box<T>.make parity).
        self.builder.position_at_end(fail_block)
        self._emit_panic("allocation failed")  # terminates with unreachable

        self.builder.position_at_end(cont_block)
        return self.builder.load(result_slot)

    def _box_allocator_saw(self, box_saw):
        """The allocator type arg of a `Box<any Trait, A>` (Global by default)."""
        trait_args = box_saw.type_args or []
        return trait_args[1] if len(trait_args) > 1 else SawType(
            TypeKind.STRUCT, struct_name="GlobalAllocator")

    def _erased_run_dtor(self, data, vtable_ptr):
        """Slot 0: run the payload's drop glue in place (from the vtable)."""
        zero = ir.Constant(self.int_type, 0)
        dtor_gep = self.builder.gep(vtable_ptr, [zero, ir.Constant(ir.IntType(32), 0)])
        dtor = self.builder.load(dtor_gep)
        self.builder.call(dtor, [data])

    def _erased_dealloc_shell(self, data, vtable_ptr, alloc_saw):
        """Slots 1/2: read size/align from the vtable and free the chunk through
        `A`. Does NOT run the payload destructor — the caller either ran it (drop)
        or moved the payload out (take-on-hit)."""
        zero = ir.Constant(self.int_type, 0)
        size_gep = self.builder.gep(vtable_ptr, [zero, ir.Constant(ir.IntType(32), 1)])
        align_gep = self.builder.gep(vtable_ptr, [zero, ir.Constant(ir.IntType(32), 2)])
        size = self.builder.load(size_gep)
        align = self.builder.load(align_gep)
        dealloc_fn = self.functions[mangle_method(mangle_type(alloc_saw), "dealloc")]
        a_self = ir.Constant(self._get_llvm_type(alloc_saw), ir.Undefined)
        self.builder.call(dealloc_fn, [a_self, data, size, align])

    # -------------------------------------------------- teardown (5)
    def _emit_erased_box_drop(self, box_ptr, box_saw):
        """Drop a `Box<any Trait, A>` at `box_ptr` (a pointer to the fat value):
        run the payload's destructor (from the vtable) in place, then dealloc the
        chunk through `A` with the vtable's size/align. Exactly-once — the fat
        pointer owns one live payload."""
        alloc_saw = self._box_allocator_saw(box_saw)
        trait_name = (box_saw.type_args or [])[0].existential_trait
        fat = self.builder.load(box_ptr)
        data = self.builder.extract_value(fat, 0)
        vtable_i8 = self.builder.extract_value(fat, 1)
        vt_ty = self._vtable_llvm_type(trait_name)
        vtable_ptr = self.builder.bitcast(vtable_i8, vt_ty.as_pointer())
        self._erased_run_dtor(data, vtable_ptr)
        self._erased_dealloc_shell(data, vtable_ptr, alloc_saw)

    # -------------------------------------------------- downcasting (design 72)
    def _generate_erased_downcast(self, expr):
        """`b.is<T>()` / `b.take<T>()` on a `Box<any Trait, A>` (design 72).

        `is` LOADS the box's vtable type-id and compares it to the compile-time
        id for the concrete `T`, yielding `Bool` (a borrow — the box stays live).

        `take` CONSUMES the box (the typechecker marked the receiver moved and
        codegen clears its drop flag). On an id HIT it moves the payload out of
        the chunk (loads the concrete `T`), frees the shell WITHOUT running the
        payload destructor (ownership transferred), and yields `Some(T)`. On a
        MISS it runs the full box drop (dtor + dealloc) and yields `None` — the
        box is consumed either way (`is<T>()` first lets callers branch without
        consuming). Returns a `T?` optional."""
        info = expr.erased_downcast
        op = info['op']
        target_saw = info['target']
        box_saw = info['box_type']
        trait_name = info['trait']
        alloc_saw = self._box_allocator_saw(box_saw)

        recv = self._generate_expression(expr.object)  # fat pointer value
        data = self.builder.extract_value(recv, 0)
        vtable_i8 = self.builder.extract_value(recv, 1)
        vt_ty = self._vtable_llvm_type(trait_name)
        vtable_ptr = self.builder.bitcast(vtable_i8, vt_ty.as_pointer())
        zero = ir.Constant(self.int_type, 0)
        tid_gep = self.builder.gep(
            vtable_ptr, [zero, ir.Constant(ir.IntType(32), 3)])  # type_id slot
        actual_id = self.builder.load(tid_gep, name="box_type_id")
        want_id = ir.Constant(self.int_type, self._type_id_for(target_saw))
        matches = self.builder.icmp_signed('==', actual_id, want_id, name="is_match")

        if op == "is":
            return self.builder.zext(matches, ir.IntType(1)) if matches.type != ir.IntType(1) else matches

        # take: build a `T?` result across a hit/miss branch.
        target_llvm = self._get_llvm_type(target_saw)
        opt_ty = ir.LiteralStructType([ir.IntType(1), target_llvm])
        result_slot = self.builder.alloca(opt_ty, name="take_result")

        hit_bb = self.builder.append_basic_block("take_hit")
        miss_bb = self.builder.append_basic_block("take_miss")
        cont_bb = self.builder.append_basic_block("take_cont")
        self.builder.cbranch(matches, hit_bb, miss_bb)

        # Hit: move the payload out, free the shell (no dtor), Some(value).
        self.builder.position_at_end(hit_bb)
        typed = self.builder.bitcast(data, target_llvm.as_pointer())
        value = self.builder.load(typed, name="take_value")
        self._erased_dealloc_shell(data, vtable_ptr, alloc_saw)
        some = ir.Constant(opt_ty, ir.Undefined)
        some = self.builder.insert_value(some, ir.Constant(ir.IntType(1), 1), 0)
        some = self.builder.insert_value(some, value, 1)
        self.builder.store(some, result_slot)
        self.builder.branch(cont_bb)

        # Miss: drop the whole box (dtor + dealloc), None.
        self.builder.position_at_end(miss_bb)
        self._erased_run_dtor(data, vtable_ptr)
        self._erased_dealloc_shell(data, vtable_ptr, alloc_saw)
        none = ir.Constant(opt_ty, ir.Undefined)
        none = self.builder.insert_value(none, ir.Constant(ir.IntType(1), 0), 0)
        self.builder.store(none, result_slot)
        self.builder.branch(cont_bb)

        self.builder.position_at_end(cont_bb)
        return self.builder.load(result_slot, name="take_opt")

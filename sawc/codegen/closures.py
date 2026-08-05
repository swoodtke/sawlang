"""
Closure generation for the Saw code generator.

This module provides mixin methods for generating closures, which are first-class
functions that can capture variables from their enclosing scope.

Closure representation:
- Closures are represented as a struct { fn_ptr, env_ptr }
- fn_ptr points to a generated function that takes (env_ptr, params...) -> ret
- env_ptr points to a struct containing captured variables

Usage:
    class CodeGenerator(ClosuresMixin, ...):
        pass
"""

from llvmlite import ir
from ast_nodes import ClosureExpr, TypeKind


class ClosuresMixin:
    """Mixin providing closure generation methods for CodeGenerator.

    Methods:
        _generate_closure: Generate code for a closure expression
        _generate_closure_call: Generate code for calling a closure
    """

    def _generate_closure(self, expr: ClosureExpr):
        """Generate code for a closure expression.

        Creates:
        1. An environment struct containing captured variables
        2. A function that takes (env_ptr, params...) and accesses captures via env
        3. A closure struct { fn_ptr, env_ptr } that can be passed around
        """
        # Determine closure parameter and return types. Prefer the typechecker's
        # resolved function signature (accurate for inferred and reference
        # parameters); fall back to annotations / Int for older paths.
        param_types = []
        param_names = []
        # Per-parameter Saw types (None if unknown); used to mark reference params.
        param_saw_types = []
        resolved = getattr(expr, 'resolved_type', None)
        resolved_params = resolved.param_types if (resolved and resolved.param_types) else None

        if expr.parameters:
            for idx, param in enumerate(expr.parameters):
                saw_t = None
                if resolved_params and idx < len(resolved_params):
                    saw_t = resolved_params[idx]
                elif param.type_annotation:
                    saw_t = param.type_annotation
                if saw_t is not None:
                    param_types.append(self._get_llvm_type(saw_t))
                else:
                    param_types.append(self.int_type)  # fallback
                param_saw_types.append(saw_t)
                param_names.append(param.name)
        elif expr.shorthand_param_count > 0:
            # Shorthand params - types should be inferred
            for i in range(expr.shorthand_param_count):
                saw_t = None
                if resolved_params and i < len(resolved_params):
                    saw_t = resolved_params[i]
                param_types.append(self._get_llvm_type(saw_t) if saw_t is not None
                                   else self.int_type)
                param_saw_types.append(saw_t)
                param_names.append(f"${i}")

        # Get return type from the resolved signature when known.
        ret_saw_type = resolved.func_return_type if resolved else None
        if ret_saw_type is not None and ret_saw_type.kind != TypeKind.VOID:
            ret_type = self._get_llvm_type(ret_saw_type)
        elif ret_saw_type is not None and ret_saw_type.kind == TypeKind.VOID:
            ret_type = ir.VoidType()
        elif expr.body.final_expr:
            ret_type = self.int_type  # Default return type
        else:
            ret_type = ir.VoidType()

        # Create environment struct type for captures
        env_ptr_type = ir.PointerType(ir.IntType(8))
        captures = expr.captures or []
        # An ESCAPING closure heap-allocates its env and joins the ImplicitCopy
        # family (design 73): the env carries a leading atomic refcount word so a
        # copy bumps it and the last owner's drop releases captures + frees the
        # block, exactly once. The word only exists when there is a heap env
        # (escaping AND captures). A capture-less closure has a null env — no
        # refcount, trivially copyable (retain/drop are null-guarded no-ops).
        escapes = getattr(expr, 'escapes', False)
        has_heap_env = escapes and bool(captures)
        cap_off = 1 if has_heap_env else 0   # captures start after the refcount word
        # Per-capture mode (design 16/29): 'ref'/'ref_var' lower to an
        # env-of-references (a pointer INTO the enclosing frame — sound because a
        # non-escaping closure cannot outlive the call); every other mode uses
        # the env-of-values path (bitwise / retain / move / copy).
        modes = getattr(expr, 'capture_modes', {}) or {}

        def _cap_base_llvm(cap_name):
            if cap_name in self.variable_types:
                return self._get_llvm_type(self.variable_types[cap_name])
            elif cap_name in self.variables:
                return self.variables[cap_name].type.pointee
            return self.int_type  # Fallback

        # Referent Saw types captured before the closure scope is reset, so the
        # body can type reads/writes through borrowed and by-value captures.
        cap_saw_types = {name: self.variable_types.get(name) for name in captures}

        if captures:
            # Build environment struct with captured variables. An escaping
            # closure's heap env leads with the atomic refcount word (design 73).
            env_field_types = [self.int_type] if has_heap_env else []
            for cap_name in captures:
                base = _cap_base_llvm(cap_name)
                if modes.get(cap_name) in ('ref', 'ref_var'):
                    env_field_types.append(ir.PointerType(base))  # env-of-reference
                else:
                    env_field_types.append(base)
            env_struct_type = ir.LiteralStructType(env_field_types)
        else:
            env_struct_type = None

        # Create unique name for closure function
        closure_name = f"__closure_{self.closure_counter}"
        self.closure_counter += 1

        # Create closure function type: (env_ptr, params...) -> ret
        fn_param_types = [env_ptr_type] + param_types
        fn_type = ir.FunctionType(ret_type, fn_param_types)

        # Create the closure function
        closure_fn = ir.Function(self.module, fn_type, name=closure_name)
        # Mark &var params noalias (arg 0 is the env pointer, so params start at
        # arg 1); same exclusivity-backed reasoning as top-level functions.
        self._mark_noalias_params(closure_fn, param_saw_types, arg_offset=1)

        # Save current builder and variables
        saved_builder = self.builder
        saved_variables = self.variables.copy()
        saved_variable_types = self.variable_types.copy()
        saved_cleanup_stack = self.cleanup_stack[:]
        saved_drop_flags = self.drop_flags
        saved_moved_variables = self.moved_variables

        # Generate closure body
        entry = closure_fn.append_basic_block(name="entry")
        # design 122 unit I: carry the enclosing function's file + line into the
        # closure so a panic raised inside it names a consistent FILE:LINE (the
        # closure has no DISubprogram of its own).
        if saved_builder is not None:
            self._di_inherit_location(closure_fn, saved_builder.function.name)
        self.builder = ir.IRBuilder(entry)
        self.variables = {}
        self.void_variables = set()
        self.variable_types = {}
        self.cleanup_stack = []
        self.drop_flags = {}
        self.moved_variables = set()

        # Set up environment access if there are captures
        if captures and env_struct_type:
            env_ptr_arg = closure_fn.args[0]
            typed_env_ptr = self.builder.bitcast(
                env_ptr_arg,
                ir.PointerType(env_struct_type),
                name="env_typed"
            )
            for i, cap_name in enumerate(captures):
                field_ptr = self.builder.gep(
                    typed_env_ptr,
                    [ir.Constant(ir.IntType(32), 0),
                     ir.Constant(ir.IntType(32), i + cap_off)],
                    name=f"cap_{cap_name}_ptr"
                )
                csaw = cap_saw_types.get(cap_name)
                if modes.get(cap_name) in ('ref', 'ref_var'):
                    # env-of-reference: the field holds a pointer to the referent
                    # in the enclosing frame. Bind the name straight to that
                    # pointer (like a `&var` param) so reads load and writes store
                    # through it — no local copy, mutations reach the real value.
                    ref_ptr = self.builder.load(field_ptr, name=f"cap_{cap_name}_ref")
                    self.variables[cap_name] = ref_ptr
                    if csaw is not None:
                        self.variable_types[cap_name] = csaw
                else:
                    # Load the captured value into a local alloca (env-of-values).
                    cap_value = self.builder.load(field_ptr, name=f"cap_{cap_name}")
                    alloca = self._entry_alloca(cap_value.type, name=cap_name)
                    self.builder.store(cap_value, alloca)
                    self.variables[cap_name] = alloca
                    if csaw is not None:
                        self.variable_types[cap_name] = csaw

        # Set up parameter access
        for i, param_name in enumerate(param_names):
            llvm_param = closure_fn.args[i + 1]  # +1 for env_ptr
            saw_t = param_saw_types[i] if i < len(param_saw_types) else None
            if saw_t is not None and saw_t.kind == TypeKind.REFERENCE:
                # Reference-capture param (design 21 item 3): the argument is
                # already a pointer to the referent. Bind the name to that
                # pointer directly (like a `&var self` receiver) so reads load
                # and writes store through it — no local copy.
                self.variables[param_name] = llvm_param
                self.variable_types[param_name] = saw_t.inner_type
            else:
                alloca = self._entry_alloca(param_types[i], name=param_name)
                self.builder.store(llvm_param, alloca)
                self.variables[param_name] = alloca
                if saw_t is not None:
                    self.variable_types[param_name] = saw_t

        # Generate body
        result = self._generate_block(expr.body)

        # Return
        if ret_type == ir.VoidType():
            if not self.builder.block.is_terminated:
                self.builder.ret_void()
        else:
            if not self.builder.block.is_terminated:
                if result is not None:
                    self.builder.ret(result)
                else:
                    # `undef`, not `0`: a degenerate fallthrough of an
                    # aggregate-returning closure — `ir.Constant(t, 0)` is invalid
                    # for a struct/enum/optional/array/tuple (DF8, same as the
                    # function/method paths).
                    self.builder.ret(ir.Constant(ret_type, ir.Undefined))

        # Restore context
        self.builder = saved_builder
        self.variables = saved_variables
        self.variable_types = saved_variable_types
        self.cleanup_stack = saved_cleanup_stack
        self.drop_flags = saved_drop_flags
        self.moved_variables = saved_moved_variables

        # Build the environment and copy captured values in. A NON-escaping
        # closure (a direct call argument, e.g. Mutex.lock's body) keeps its env
        # on the stack — it is consumed before the frame returns, so captures are
        # borrowed and no retain/teardown is needed. An ESCAPING closure (design
        # 21b E1: bound/returned/passed to spawn) heap-allocates its env via
        # saw_alloc and transfers each capture in per the value-transfer rules:
        # ImplicitCopy captures are retained (copy() == refcount bump); trivial
        # captures are copied bitwise. A generated env-destructor runs the
        # captures' drop glue exactly once and frees the block; for spawn the
        # trampoline invokes it on the task thread after the body returns.
        env_dtor = None
        if captures and env_struct_type:
            if escapes:
                env_size = self._abi_size(env_struct_type)
                # Panics rather than storing through the NULL a refused
                # allocation returns (design 123, infallible tier: a closure
                # literal has no signature to report an OOM through).
                raw = self._alloc_or_panic(
                    env_size, 16, "closure environment",
                    line=getattr(expr, 'line', 0))
                env_alloca = self.builder.bitcast(
                    raw, ir.PointerType(env_struct_type), name="env_heap")
                # Seed the atomic refcount word (field 0) to 1 — this creation is
                # the first owner (design 73). Later copies bump it; the last
                # owner's drop decrements to 0 and runs the dtor.
                rc_ptr = self.builder.gep(
                    env_alloca,
                    [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)],
                    name="env_refcount")
                self.builder.store(ir.Constant(self.int_type, 1), rc_ptr)
            else:
                env_alloca = self._entry_alloca(env_struct_type, name="closure_env")
            for i, cap_name in enumerate(captures):
                if cap_name not in self.variables:
                    continue
                field_ptr = self.builder.gep(
                    env_alloca,
                    [ir.Constant(ir.IntType(32), 0),
                     ir.Constant(ir.IntType(32), i + cap_off)],
                    name=f"env_field_{i}"
                )
                mode = modes.get(cap_name, 'plain')
                if mode in ('ref', 'ref_var'):
                    # env-of-reference: store the pointer to the enclosing binding
                    # itself (self.variables holds its address), not a loaded copy.
                    self.builder.store(self.variables[cap_name], field_ptr)
                    continue
                cap_value = self.builder.load(self.variables[cap_name], name=f"load_{cap_name}")
                cap_saw = cap_saw_types.get(cap_name)
                if mode == 'move':
                    # Ownership transfers into the env; the source is moved-from,
                    # so no retain — and the CREATING frame must NOT drop it (design
                    # 71: the closure's own drop, via the env destructor, releases
                    # it exactly once). Clear the source binding's drop flag (or mark
                    # it statically moved) so the frame's scope-exit cleanup skips it.
                    # Without this the source is released early at frame exit AND, on
                    # the spawn path, again by the trampoline's dtor — a double free.
                    if escapes:
                        src_flag = self.drop_flags.get(cap_name)
                        if src_flag is not None:
                            self.builder.store(ir.Constant(ir.IntType(1), 0), src_flag)
                        self.moved_variables.add(cap_name)
                elif mode == 'copy' and cap_saw is not None:
                    # Explicit deep copy (ExplicitCopy `.copy()` / ImplicitCopy retain).
                    cap_value = self._emit_copy_value(cap_value, cap_saw)
                elif escapes and cap_saw is not None:
                    # Plain capture into a heap env: retain ImplicitCopy captures
                    # (no-op for trivial types).
                    cap_value = self._generate_copy(cap_value, cap_saw)
                self.builder.store(cap_value, field_ptr)
            env_ptr_val = self.builder.bitcast(env_alloca, env_ptr_type, name="env_ptr")
            if escapes:
                env_dtor = self._generate_env_dtor(
                    env_struct_type, captures, closure_name, cap_saw_types, modes,
                    cap_off)
        else:
            env_ptr_val = ir.Constant(env_ptr_type, None)

        # dtor_ptr: the env destructor for an escaping closure that owns a heap env
        # (design 71). Null for a stack/no env — dropping such a closure is a no-op.
        # The value carries its own destructor so it can be dropped wherever it
        # flows (bound / struct field / Vector / returned).
        dtor_ptr_type = ir.PointerType(ir.FunctionType(ir.VoidType(), [env_ptr_type]))
        dtor_val = (env_dtor if env_dtor is not None
                    else ir.Constant(dtor_ptr_type, None))

        # Create closure struct: { fn_ptr, env_ptr, dtor_ptr }
        closure_type = ir.LiteralStructType(
            [ir.PointerType(fn_type), env_ptr_type, dtor_ptr_type])
        closure_val = ir.Constant(closure_type, ir.Undefined)
        closure_val = self.builder.insert_value(closure_val, closure_fn, 0, name="closure_fn")
        closure_val = self.builder.insert_value(closure_val, env_ptr_val, 1, name="closure_env")
        closure_val = self.builder.insert_value(closure_val, dtor_val, 2, name="closure_dtor")

        # Expose the generated function and env pointer to `spawn` codegen, which
        # calls the closure body directly from a trampoline and needs the env's
        # heap pointer to hand to the task thread. Side table, not an AST field
        # (design 126 R1): LLVM values must never ride the tree that the effect
        # and monomorphization passes walk.
        self.closure_values[expr.node_id] = (closure_fn, env_ptr_val, env_dtor)

        return closure_val

    def _generate_env_dtor(self, env_struct_type, captures, closure_name,
                           cap_saw_types=None, modes=None, cap_off=0):
        """Emit the environment destructor for an escaping closure (design 21b E1
        / design 73).

        Signature `void (i8* env)`: runs drop glue for each cleanup-needing
        capture (releasing retained ImplicitCopy captures such as an `Arc`)
        exactly once, then frees the heap env with `saw_dealloc`. It is the
        run-at-refcount-zero teardown: `_emit_closure_drop_at` (and the spawn
        trampoline) atomically decrement the env's leading refcount word and call
        this only when the LAST owner drops, so it runs exactly once regardless of
        how many copies the ImplicitCopy closure spawned. `cap_off` is the field
        offset the captures start at (1 past the refcount word for a heap env).
        """
        i8 = ir.IntType(8)
        i8ptr = i8.as_pointer()
        i64 = self.int_type  # design 47: saw_dealloc size/align are platform-width
        void = ir.VoidType()
        env_size = self._abi_size(env_struct_type)

        fn = ir.Function(self.module, ir.FunctionType(void, [i8ptr]),
                         name=f"{closure_name}_env_dtor")
        saved_builder = self.builder
        b = ir.IRBuilder(fn.append_basic_block("entry"))
        self.builder = b
        cap_saw_types = cap_saw_types or {}
        modes = modes or {}
        env_typed = b.bitcast(fn.args[0], ir.PointerType(env_struct_type), name="env")
        for i, cap_name in enumerate(captures):
            # Borrow captures own nothing — never drop them.
            if modes.get(cap_name) in ('ref', 'ref_var'):
                continue
            cap_saw = cap_saw_types.get(cap_name, self.variable_types.get(cap_name))
            if cap_saw is not None and self._needs_cleanup(cap_saw):
                field_ptr = b.gep(
                    env_typed,
                    [ir.Constant(ir.IntType(32), 0),
                     ir.Constant(ir.IntType(32), i + cap_off)],
                    name=f"env_drop_{i}")
                self._emit_drop_at(field_ptr, cap_saw)
        b.call(self.functions["__saw_rt_dealloc"],
               [fn.args[0], ir.Constant(i64, env_size), ir.Constant(i64, 16)])
        b.ret_void()
        self.builder = saved_builder
        return fn

    def _generate_closure_call(self, closure_val, arguments):
        """Generate code for calling a closure stored in a variable.

        Extracts fn_ptr and env_ptr from the closure struct, then calls
        fn_ptr(env_ptr, args...).
        """
        # Extract fn_ptr and env_ptr from closure struct
        fn_ptr = self.builder.extract_value(closure_val, 0, name="fn_ptr")
        env_ptr = self.builder.extract_value(closure_val, 1, name="env_ptr")

        # Generate argument values
        arg_vals = [self._generate_expression(arg) for arg in arguments]

        # Call: fn_ptr(env_ptr, arg1, arg2, ...)
        return self.builder.call(fn_ptr, [env_ptr] + arg_vals, name="closure_call")

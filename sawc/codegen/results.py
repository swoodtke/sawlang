"""
Result type handling for the Saw code generator.

This module provides mixin methods for generating code that handles Result<T, E>
types and try expressions (try, try?, try!).

Result representation (same as enums):
- Tagged union: { i32, [max_bytes x i8] }
- Ok = tag 0, Err = tag 1

Usage:
    class CodeGenerator(ResultsMixin, ...):
        pass
"""

from llvmlite import ir
from ast_nodes import TryExpr, TryCatchExpr, SawType, TypeKind, ResultOkWrap, ResultErrWrap
from .calls import PreparedValue
from .mangle import mangle_named


class ResultsMixin:
    """Mixin providing Result type handling methods for CodeGenerator.

    Methods:
        _generate_try_expr: Generate code for try/try?/try! expressions
        _generate_try_catch_expr: Generate code for try-catch blocks
        _extract_result_ok_value: Extract Ok value from Result
        _extract_result_err_value: Extract Err value from Result
        _create_result_ok: Create a Result.Ok(value)
        _create_result_err: Create a Result.Err(error)
    """

    def _generate_try_expr(self, expr: TryExpr):
        """Generate code for try/try?/try! expressions."""
        result_val = self._generate_expression(expr.expr)

        # Resolve the concrete Result instantiation. Prefer the typechecker
        # annotation (the concrete `Result<T, E>` SawType): matching by LLVM type
        # alone is AMBIGUOUS because distinct instantiations share a layout —
        # `Result<Int, Int>` and `Result<String, E>` are both `{ i32, [8 x i8] }`,
        # so LLVM-type matching would pick whichever was registered first and
        # extract the Ok/Err payload as the wrong type (e.g. an Int read as a
        # String pointer -> crash). The name-based path keys off the actual type.
        result_enum_name = None
        annotated = expr.result_enum_type
        if annotated is not None and annotated.is_result():
            candidate = self._get_result_enum_name(annotated)
            if candidate in self.enum_types:
                result_enum_name = candidate

        if result_enum_name is None:
            # Fallback: match by LLVM type (ambiguous across same-layout
            # instantiations, but the only option when the annotation is absent).
            for name, (llvm_type, _, _) in self.enum_types.items():
                if name.startswith("Result$") and llvm_type == result_val.type:
                    result_enum_name = name
                    break

        if result_enum_name is None:
            # Try to find from type context
            for name in self.enum_types:
                if name.startswith("Result"):
                    result_enum_name = name
                    break

        if result_enum_name is None:
            raise ValueError(f"Could not find Result enum type for try expression at line {expr.line}")

        llvm_enum_type, variant_tags, variant_info = self.enum_types[result_enum_name]

        # Extract the tag (Ok=0, Err=1)
        tag = self.builder.extract_value(result_val, 0, name="result_tag")
        ok_tag = ir.Constant(ir.IntType(32), variant_tags["Ok"])
        is_ok = self.builder.icmp_unsigned('==', tag, ok_tag, name="is_ok")

        if expr.variant == "force":
            # try! - panic on Err
            return self._generate_try_force(result_val, is_ok, expr, result_enum_name)

        elif expr.variant == "optional":
            # try? - convert to Optional
            return self._generate_try_optional(result_val, is_ok, expr, result_enum_name)

        else:  # "propagate"
            if expr.catch_block:
                # try expr catch { ... } - local error handling
                return self._generate_try_with_inline_catch(result_val, is_ok, expr, result_enum_name)
            else:
                # try expr - propagate error to caller
                return self._generate_try_propagate(result_val, is_ok, expr, result_enum_name)

    def _generate_try_force(self, result_val, is_ok, expr: TryExpr, result_enum_name: str):
        """Generate code for try! (force unwrap, panic on Err)."""
        func = self.builder.function
        ok_bb = func.append_basic_block(name="try_ok")
        panic_bb = func.append_basic_block(name="try_panic")

        self.builder.cbranch(is_ok, ok_bb, panic_bb)

        # Panic block: emit the panic via the saw_panic seam.
        self.builder.position_at_end(panic_bb)
        self._emit_try_force_panic(result_val, expr, result_enum_name)

        # OK block - extract value
        self.builder.position_at_end(ok_bb)
        return self._extract_result_ok_value(result_val, result_enum_name)

    def _emit_try_force_panic(self, result_val, expr: TryExpr,
                              result_enum_name: str):
        """Panic out of a `try!` that met an `Err`, NAMING the error (DF-245b).

        `try!` is the only consumer of a `Result` that does not hand the payload
        on — `try`, `try?`, `catch` and `main`'s Err exit all do — so it was the
        one place a failure arrived complete and was reported as `try! failed`
        and nothing else. That is also the spelling design 234 migrates a call
        site to when it does not want to handle the failure, which is what makes
        the message quality the point rather than a papercut: `try! v.push(x)`
        must say what `Vector.push`'s panic said.

        The error is rendered after the fixed text, through the SAME stack-scratch
        walk `panic("...{}", e)` uses (`_render_argument` -> design 137), so the
        alloc-free and denied-allocator paths keep working and an erased
        `Box<any Error>` renders through its vtable exactly as `"{e}"` does. The
        scratch lands in THIS block, not the entry block: it ends in
        `unreachable`, so a function that merely contains a `try!` pays no frame
        bytes for the message.

        An error type the format walk cannot render — a struct or enum with no
        `Printable` conformance, which `E` is not bounded to have — keeps the
        bare text. Nothing is guessed about a type that never said how it reads.
        """
        _, _, variant_info = self.enum_types[result_enum_name]
        err_params = variant_info["Err"]
        err_type = err_params[0][1] if err_params else None
        renderable = err_type is not None and (
            self.namespace.is_printable(err_type)
            or self._is_builtin_interp_type(err_type))
        if not renderable:
            self._emit_panic("try! failed", line=expr.line)
            return

        err_value = self._extract_result_err_value(result_val, result_enum_name)
        rendered = PreparedValue(value=err_value, resolved_type=err_type,
                                 line=expr.line, column=expr.column)
        prefix_ptr, prefix_len = self._raw_bytes_ptr(
            self._panic_location_prefix(expr.line) + "try! failed: ")
        self._emit_runtime_panic(
            [(prefix_ptr, prefix_len),
             self._render_argument(rendered, in_entry=False)])

    def _generate_try_optional(self, result_val, is_ok, expr: TryExpr, result_enum_name: str):
        """Generate code for try? (convert Result<T, E> to T?)."""
        func = self.builder.function
        ok_bb = func.append_basic_block(name="try_some")
        err_bb = func.append_basic_block(name="try_none")
        merge_bb = func.append_basic_block(name="try_merge")

        self.builder.cbranch(is_ok, ok_bb, err_bb)

        # OK block - wrap in Some
        self.builder.position_at_end(ok_bb)
        ok_value = self._extract_result_ok_value(result_val, result_enum_name)
        some_result = self._wrap_in_optional(ok_value)
        self.builder.branch(merge_bb)
        ok_end_bb = self.builder.block

        # Err block - return None
        self.builder.position_at_end(err_bb)
        none_result = self._create_none_for_type(ok_value.type)
        self.builder.branch(merge_bb)
        err_end_bb = self.builder.block

        # Merge
        self.builder.position_at_end(merge_bb)
        phi = self.builder.phi(some_result.type, name="try_result")
        phi.add_incoming(some_result, ok_end_bb)
        phi.add_incoming(none_result, err_end_bb)
        return phi

    def _generate_try_propagate(self, result_val, is_ok, expr: TryExpr, result_enum_name: str):
        """Generate code for try (propagate Err to caller or to enclosing catch)."""
        func = self.builder.function
        ok_bb = func.append_basic_block(name="try_ok")
        err_bb = func.append_basic_block(name="try_err")

        self.builder.cbranch(is_ok, ok_bb, err_bb)

        # Err block
        self.builder.position_at_end(err_bb)
        err_value = self._extract_result_err_value(result_val, result_enum_name)

        # The concrete error type of this Result is carried structurally in the
        # enum's variant info (Err -> [("error", <SawType>)]). We use it directly
        # rather than parsing it back out of the mangled enum name.
        _, _, result_variant_info = self.enum_types[result_enum_name]
        concrete_err_type = result_variant_info["Err"][0][1]

        # design 234 §3: the ROUTING clause `try(as LocalError.Alloc) f()`
        # converts the error channel before anything downstream looks at it —
        # the caller's signature, an enclosing catch's union, an erasure into
        # `Box<any Error>`. So it happens FIRST, and everything below runs on
        # the routed value exactly as it would on an unrouted one.
        if expr.route_target is not None and expr.route_case is not None:
            err_value = self._build_enum_case_value(
                err_value, expr.route_target, expr.route_case)
            concrete_err_type = expr.route_target

        # Check if we have an enclosing catch block
        catch_ctx = getattr(self, '_catch_context', None)
        if catch_ctx:
            # Unpack context - may have 2, 4 or 5 elements depending on version
            if len(catch_ctx) == 5:
                (catch_bb, err_alloca_ptr, error_type, error_types,
                 catch_cleanup_depth) = catch_ctx
            elif len(catch_ctx) == 4:
                catch_bb, err_alloca_ptr, error_type, error_types = catch_ctx
                catch_cleanup_depth = None
            else:
                catch_bb, err_alloca_ptr = catch_ctx
                error_type, error_types = None, []
                catch_cleanup_depth = None

            # Determine the value to store
            value_to_store = err_value
            store_type = err_value.type

            # If multiple error types, wrap in union enum
            if len(error_types) > 1 and error_type and error_type.enum_name:
                value_to_store = self._wrap_error_in_union(err_value, error_type, concrete_err_type)
                store_type = value_to_store.type

            # Create error alloca at function entry if not exists yet
            if err_alloca_ptr[0] is None:
                # Save position, allocate at entry, restore position
                saved_block = self.builder.block
                entry_bb = func.entry_basic_block
                # Position at start of entry block (allocas go at the beginning)
                self.builder.position_at_start(entry_bb)
                err_alloca_ptr[0] = self._entry_alloca(store_type, name="caught_error")
                self.builder.position_at_end(saved_block)

            self.builder.store(value_to_store, err_alloca_ptr[0])
            # DF-218v: the try body's locals die on THIS edge, exactly as they
            # would on the fall-through out of the same block. The error edge
            # was the THIRD nonlocal exit that is not a return (after DF-218r's
            # `break` and `continue`), and the only one that LEAKED: the OK path
            # popped the scope normally and the propagating no-catch shape below
            # runs `_cleanup_all_scopes`, so this branch alone left the block
            # with nothing dropped.
            #
            # Order: the in-flight error is COPIED into `caught_error` above,
            # before any drop runs, so what the catch receives is already out of
            # the scopes being released. Statement temporaries are drained
            # first, then the scopes innermost-first — the same sequence
            # `return` and `break` run.
            if catch_cleanup_depth is not None:
                if self.statement_temps:
                    for slot, temp_type in reversed(self.statement_temps):
                        self._emit_drop_at(slot, temp_type)
                    self.statement_temps = []
                self._cleanup_to_depth(catch_cleanup_depth)
            self.builder.branch(catch_bb)
        else:
            # No enclosing catch - propagate to caller. Erased Result (design
            # 56): if the enclosing function returns `Result<_, Box<any Trait>>`
            # and this callee's error is concrete, erase it into a fresh box at
            # the propagation edge (re-box). A callee already returning the box
            # passes straight through (no re-box) — no erase_propagate is set.
            erase = expr.erase_propagate
            if erase is not None:
                err_value = self._erase_value_to_box(
                    err_value, erase['concrete'], erase['trait'], erase['allocator'])
            caller_result = self._create_result_err_for_return(err_value)
            self._cleanup_all_scopes()
            # design 221 unit B4: a `try` inside `main` is a RETURN, and the
            # third position that leaves the C entry — the funnel's own sweep
            # of `builder.ret` sites turned it up. Unrouted, it emitted
            # `ret {i32, [8 x i8]}` out of an `i32` function and llvmlite
            # refused the module.
            if self._is_c_entry(func):
                self._emit_main_exit_return(caller_result)
            else:
                self.builder.ret(caller_result)

        # OK block - continue with unwrapped value
        self.builder.position_at_end(ok_bb)
        return self._extract_result_ok_value(result_val, result_enum_name)

    def _generate_try_with_inline_catch(self, result_val, is_ok, expr: TryExpr, result_enum_name: str):
        """Generate code for try expr catch { ... }."""
        func = self.builder.function
        ok_bb = func.append_basic_block(name="try_ok")
        catch_bb = func.append_basic_block(name="try_catch")
        merge_bb = func.append_basic_block(name="try_merge")

        self.builder.cbranch(is_ok, ok_bb, catch_bb)

        # OK block
        self.builder.position_at_end(ok_bb)
        ok_value = self._extract_result_ok_value(result_val, result_enum_name)
        self.builder.branch(merge_bb)
        ok_end_bb = self.builder.block

        # Catch block - extract error and make available as 'error' variable
        self.builder.position_at_end(catch_bb)
        err_value = self._extract_result_err_value(result_val, result_enum_name)

        # Create 'error' variable
        error_alloca = self._entry_alloca(err_value.type, name="error")
        self.builder.store(err_value, error_alloca)
        old_error = self.variables.get("error")
        self.variables["error"] = error_alloca

        # Generate catch block
        catch_result = self._generate_block(expr.catch_block)

        # Restore old 'error' if any
        if old_error is not None:
            self.variables["error"] = old_error
        elif "error" in self.variables:
            del self.variables["error"]

        # Ensure catch result has same type as ok_value
        if catch_result is not None and catch_result.type != ok_value.type:
            # Type mismatch - should have been caught by typechecker
            pass

        # A DIVERGING catch arm — `try f() catch { return fallback }`, or one
        # ending in a `panic`/`break`/`continue` — already terminated its block,
        # so it reaches no merge and contributes no incoming value. Branching
        # anyway asserted inside llvmlite and surfaced as an internal compiler
        # error with an EMPTY message (DF-196c). The block form of try/catch has
        # guarded this since it was written; this one had not.
        catch_diverged = self.builder.block.is_terminated
        if not catch_diverged:
            self.builder.branch(merge_bb)
        catch_end_bb = self.builder.block

        # Merge
        self.builder.position_at_end(merge_bb)
        phi = self.builder.phi(ok_value.type, name="try_catch_result")
        phi.add_incoming(ok_value, ok_end_bb)
        if catch_diverged:
            pass
        elif catch_result is not None:
            phi.add_incoming(catch_result, catch_end_bb)
        else:
            # Catch didn't return a value, use placeholder
            phi.add_incoming(ir.Constant(ok_value.type, ir.Undefined), catch_end_bb)
        return phi

    def _generate_try_catch_expr(self, expr: TryCatchExpr):
        """Generate code for try-catch block expression: try { ... } catch { ... }

        Sets up catch context so that try expressions (without inline catch)
        inside the try block will jump to the catch block on error.
        """
        func = self.builder.function

        # Create blocks
        catch_bb = func.append_basic_block(name="catch")
        merge_bb = func.append_basic_block(name="try_catch_merge")

        # Get error type info from typechecker (set in _check_try_catch_expr)
        error_type = expr.error_type
        error_types = getattr(expr, 'error_types', [])
        is_union = len(error_types) > 1

        # If union type, ensure it's monomorphized so we have the LLVM type
        if is_union and error_type and error_type.enum_name:
            self._ensure_enum_monomorphized(error_type.enum_name, error_type, error_types)

        # Use a mutable list so try expressions can set the alloca when they know the error type
        # Also pass error type info for union wrapping
        err_alloca_ptr = [None]  # Will be set by first try expression that fails

        # Save old catch context and set new one.
        # Context: (catch_bb, err_alloca_ptr, error_type, error_types,
        #           cleanup_depth).
        # DF-218v: the depth is recorded HERE, before `_generate_block` pushes
        # the try body's own scope, so the error edge unwinds everything the
        # body opened and nothing outside it. Same discipline as a loop's entry
        # depth on `loop_stack` (DF-218r) — a catch block is a SIBLING scope,
        # not a nested one, so the branch to it really does leave them all.
        old_catch_ctx = getattr(self, '_catch_context', None)
        self._catch_context = (catch_bb, err_alloca_ptr, error_type,
                               error_types, len(self.cleanup_stack))

        # Generate try block
        try_result = self._generate_block(expr.try_block)
        try_end_bb = self.builder.block

        # Only branch to merge if we didn't already terminate
        if not self.builder.block.is_terminated:
            self.builder.branch(merge_bb)
            try_end_bb = self.builder.block

        # Restore old catch context
        self._catch_context = old_catch_ctx

        # Generate catch block
        self.builder.position_at_end(catch_bb)

        # Make the caught error available under the binding's own NAME. Usually
        # `error`; the coroutine transform renames it when two catch blocks in
        # one body would otherwise share a frame field (design 196 unit 3), and
        # the typechecker defines the same `error_binding or "error"` name in the
        # catch scope — so reading it from the node is what keeps the two agreed.
        error_name = expr.error_binding or "error"
        if err_alloca_ptr[0] is not None:
            old_error = self.variables.get(error_name)
            self.variables[error_name] = err_alloca_ptr[0]

            # Generate catch block code
            catch_result = self._generate_block(expr.catch_block)
            catch_end_bb = self.builder.block

            # Restore old binding if any
            if old_error is not None:
                self.variables[error_name] = old_error
            elif error_name in self.variables:
                del self.variables[error_name]
        else:
            # No try expressions in the block (unusual) - just generate catch code
            catch_result = self._generate_block(expr.catch_block)
            catch_end_bb = self.builder.block

        # Only branch to merge if we didn't already terminate
        if not self.builder.block.is_terminated:
            self.builder.branch(merge_bb)
            catch_end_bb = self.builder.block

        # Merge block
        self.builder.position_at_end(merge_bb)

        # If both branches produce values, create a phi node
        if try_result is not None and catch_result is not None:
            if try_result.type == catch_result.type:
                phi = self.builder.phi(try_result.type, name="try_catch_result")
                phi.add_incoming(try_result, try_end_bb)
                phi.add_incoming(catch_result, catch_end_bb)
                return phi

        return try_result

    def _is_void_payload(self, params) -> bool:
        """Whether a Result arm's payload is dataless — every field lowers to
        Void (design 92: the Ok arm of `Result<Void, E>`). Such an arm carries
        the tag only."""
        if not params:
            return True
        return all(isinstance(self._get_llvm_type(t), ir.VoidType) for _, t in params)

    def _extract_result_ok_value(self, result_val, result_enum_name: str):
        """Extract the Ok value from a Result."""
        llvm_enum_type, variant_tags, variant_info = self.enum_types[result_enum_name]
        ok_params = variant_info["Ok"]

        # design 92: a `Result<Void, E>` Ok arm carries no value — there is
        # nothing to extract. Return None (the Void placeholder); callers in a
        # Void context (e.g. `try!` as a statement) discard it.
        if self._is_void_payload(ok_params):
            return None

        # Extract payload
        payload_bytes = self.builder.extract_value(result_val, 1, name="ok_payload")

        # Cast to appropriate struct type
        param_types = [self._get_llvm_type(t) for _, t in ok_params]
        param_struct_type = ir.LiteralStructType(param_types)

        # Store bytes to memory, then load as struct
        payload_alloca = self._entry_alloca(llvm_enum_type.elements[1], name="ok_payload_alloca", align=8)
        self.builder.store(payload_bytes, payload_alloca)
        struct_ptr = self.builder.bitcast(payload_alloca,
                                          ir.PointerType(param_struct_type),
                                          name="ok_struct_ptr")

        # Extract the 'value' field (index 0)
        field_ptr = self.builder.gep(struct_ptr,
                                    [ir.Constant(ir.IntType(32), 0),
                                     ir.Constant(ir.IntType(32), 0)],
                                    inbounds=True)
        return self.builder.load(field_ptr, name="ok_value")

    def _extract_result_err_value(self, result_val, result_enum_name: str):
        """Extract the Err value from a Result."""
        llvm_enum_type, variant_tags, variant_info = self.enum_types[result_enum_name]
        err_params = variant_info["Err"]

        # Extract payload
        payload_bytes = self.builder.extract_value(result_val, 1, name="err_payload")

        # Cast to appropriate struct type
        param_types = [self._get_llvm_type(t) for _, t in err_params]
        param_struct_type = ir.LiteralStructType(param_types)

        # Store bytes to memory, then load as struct
        payload_alloca = self._entry_alloca(llvm_enum_type.elements[1], name="err_payload_alloca", align=8)
        self.builder.store(payload_bytes, payload_alloca)
        struct_ptr = self.builder.bitcast(payload_alloca,
                                          ir.PointerType(param_struct_type),
                                          name="err_struct_ptr")

        # Extract the 'error' field (index 0)
        field_ptr = self.builder.gep(struct_ptr,
                                    [ir.Constant(ir.IntType(32), 0),
                                     ir.Constant(ir.IntType(32), 0)],
                                    inbounds=True)
        return self.builder.load(field_ptr, name="err_value")

    def _create_none_for_type(self, inner_type):
        """Create a None optional value for the given inner type."""
        optional_type = ir.LiteralStructType([ir.IntType(1), inner_type])
        result = ir.Constant(optional_type, ir.Undefined)
        result = self.builder.insert_value(result, ir.Constant(ir.IntType(1), 0), 0)
        return result

    def _create_result_err_for_return(self, err_value, result_type=None):
        """Create a Result.Err for the given (or current) function's return type.

        `result_type` overrides `current_return_type`: the coroutine transform
        rewrites `return <ResultErrWrap>` into a store to the frame's result slot
        inside `resume` (whose own return type is `Poll`, not the Result), so
        the wrap node's stored `result_type` is the authority there (design 92)."""
        # Prefer current_return_type — during generic monomorphization it is the
        # SUBSTITUTED concrete Result (the wrap node still carries the generic
        # template). Fall back to the node's type only when current_return_type is
        # not a Result: the coroutine-transform resume case, where `return` was
        # rewritten to a result-slot store and current_return_type is `Poll`.
        if self.current_return_type and self.current_return_type.is_result():
            result_type = self.current_return_type
        if not result_type or not result_type.is_result():
            raise ValueError("Cannot create Result.Err outside Result-returning function")

        # Find the monomorphized Result type for the return type
        result_enum_name = self._get_result_enum_name(result_type)

        llvm_enum_type, variant_tags, variant_info = self.enum_types[result_enum_name]

        # Create the Result value
        result_val = ir.Constant(llvm_enum_type, ir.Undefined)

        # Set tag to Err (1)
        err_tag = ir.Constant(ir.IntType(32), variant_tags["Err"])
        result_val = self.builder.insert_value(result_val, err_tag, 0)

        # Create payload struct for Err
        err_params = variant_info["Err"]
        param_types = [self._get_llvm_type(t) for _, t in err_params]
        param_struct_type = ir.LiteralStructType(param_types)

        param_struct = ir.Constant(param_struct_type, ir.Undefined)
        param_struct = self.builder.insert_value(param_struct, err_value, 0)

        # Convert struct to bytes and store in payload. The scratch slot MUST be
        # sized to the FULL payload `[N x i8]` (the biggest variant), not the
        # smaller Err variant struct: the load below reads all N bytes, so an
        # alloca of only the variant struct is read out of bounds past the slot
        # (design 94 — the create/extract asymmetry). Alloca the full payload,
        # store the variant struct into its front, load the whole thing back.
        payload_type = llvm_enum_type.elements[1]
        payload_alloca = self._entry_alloca(payload_type, name="err_struct_alloca", align=8)
        struct_ptr = self.builder.bitcast(payload_alloca, ir.PointerType(param_struct_type))
        self.builder.store(param_struct, struct_ptr)

        payload_bytes = self.builder.load(payload_alloca, name="err_bytes")

        result_val = self.builder.insert_value(result_val, payload_bytes, 1)
        return result_val

    def _create_result_ok_for_return(self, ok_value, result_type=None):
        """Create a Result.Ok for the given (or current) function's return type.

        `result_type` overrides `current_return_type` — see
        `_create_result_err_for_return` (the coroutine-transform result-slot case)."""
        # See _create_result_err_for_return for the precedence rationale.
        if self.current_return_type and self.current_return_type.is_result():
            result_type = self.current_return_type
        if not result_type or not result_type.is_result():
            raise ValueError("Cannot create Result.Ok outside Result-returning function")

        result_enum_name = self._get_result_enum_name(result_type)

        llvm_enum_type, variant_tags, variant_info = self.enum_types[result_enum_name]

        # Create the Result value
        result_val = ir.Constant(llvm_enum_type, ir.Undefined)

        # Set tag to Ok (0)
        ok_tag = ir.Constant(ir.IntType(32), variant_tags["Ok"])
        result_val = self.builder.insert_value(result_val, ok_tag, 0)

        # design 92: a `Result<Void, E>` Ok has no payload — the tag alone is
        # the whole value (the byte array stays undef; the Err arm sizes it).
        ok_params = variant_info["Ok"]
        if self._is_void_payload(ok_params):
            return result_val

        # Create payload struct for Ok
        param_types = [self._get_llvm_type(t) for _, t in ok_params]
        param_struct_type = ir.LiteralStructType(param_types)

        param_struct = ir.Constant(param_struct_type, ir.Undefined)
        param_struct = self.builder.insert_value(param_struct, ok_value, 0)

        # Convert struct to bytes and store in payload. Size the scratch to the
        # FULL payload `[N x i8]`, not the smaller Ok variant struct — see
        # _create_result_err_for_return (design 94: the load reads all N bytes).
        payload_type = llvm_enum_type.elements[1]
        payload_alloca = self._entry_alloca(payload_type, name="ok_struct_alloca", align=8)
        struct_ptr = self.builder.bitcast(payload_alloca, ir.PointerType(param_struct_type))
        self.builder.store(param_struct, struct_ptr)

        payload_bytes = self.builder.load(payload_alloca, name="ok_bytes")

        result_val = self.builder.insert_value(result_val, payload_bytes, 1)
        return result_val

    def visit_ResultOkWrap(self, expr: ResultOkWrap):
        """Generate code for ResultOkWrap (T -> Result<T, E> as Ok).

        This is inserted by the typechecker when a value of type T
        is returned from a function with return type Result<T, E>.

        Design 40 item 5 (L10): the inner value escapes into the Ok payload —
        this is a transfer site. Generate it through _gen_transfer_value so an
        owned Copy value (`return s` where `s: String`) is retained
        exactly as a direct return would retain it. Without the retain, scope
        cleanup releases the local and frees the buffer the payload still points
        at (premature free). `return move s` still works: the MoveExpr inside is
        not retained and the local is marked moved so cleanup skips it.
        """
        # design 92: a value-less Ok (bare `return` in a `Result<Void, E>`
        # function) has no inner expression to transfer — the Ok is the tag alone.
        rtype = expr.result_type
        if expr.value is None:
            return self._create_result_ok_for_return(None, rtype)
        value = self._gen_transfer_value(expr.value)
        return self._create_result_ok_for_return(value, rtype)

    def visit_ResultErrWrap(self, expr: ResultErrWrap):
        """Generate code for ResultErrWrap (E -> Result<T, E> as Err).

        This is inserted by the typechecker when a value of type E
        is returned from a function with return type Result<T, E>.

        The Err payload is a transfer site too (design 40 item 5): retain an
        owned Copy error value so scope cleanup does not free it early.
        """
        value = self._gen_transfer_value(expr.value)
        return self._create_result_err_for_return(value, expr.result_type)

    def visit_ErasedErrWrap(self, expr):
        """Generate code for ErasedErrWrap (design 56): erase a concrete `E`
        into a `Box<any Trait>` (through the allocator, Global by default), then
        build the Err payload from the fat pointer."""
        value = self._gen_transfer_value(expr.value)
        alloc_saw = expr.allocator or SawType(TypeKind.STRUCT, struct_name="GlobalAllocator")
        fat = self._erase_value_to_box(value, expr.concrete_err,
                                       expr.trait_name, alloc_saw)
        # Pass the wrap's OWN `result_type`, exactly as `visit_ResultErrWrap`
        # does. `current_return_type` still wins where it is a Result (the
        # generic-monomorphization case), and the node's type is the authority
        # where it is not — the coroutine transform rewrites `return <wrap>` into
        # a store to the frame's result slot inside `resume`, whose return type
        # is `Poll`. Omitting it made an erased-error return in a SUSPENDING
        # body an ICE (DF-192c) while its concrete sibling worked.
        return self._create_result_err_for_return(fat, expr.result_type)

    def _get_result_enum_name(self, result_type: SawType) -> str:
        """Get the monomorphized enum name for a Result type."""
        if not result_type.is_result():
            raise ValueError(f"Expected Result type, got {result_type}")

        ok_type = result_type.unwrap_result_ok()
        err_type = result_type.unwrap_result_err()

        # Build the canonical mangled name. This MUST match the name under which
        # the monomorphized Result enum is registered (via _ensure_monomorphized_enum
        # -> mangle_named), so producer and consumer never diverge. Canonicalize the
        # payload types first — filling omitted trailing default type args at every
        # nesting level, e.g. a raw method-annotation `Box<any Error>` -> arity-2
        # `Box<any Error, Global>` (design 68) — so the name computed here from a
        # raw `current_return_type` matches the registration, which canonicalizes.
        ok_type = self._canonicalize_type_kind(ok_type)
        err_type = self._canonicalize_type_kind(err_type)
        return mangle_named("Result", [ok_type, err_type])

    def _ensure_enum_monomorphized(self, enum_name: str, saw_type: SawType, error_types: list = None):
        """Ensure a synthetic enum (like error union) is registered in enum_types.

        This handles enums created by the typechecker (like _CatchError_123)
        that aren't from source code.
        """
        if enum_name in self.enum_types:
            return  # Already registered

        if error_types is None:
            raise ValueError(f"Cannot monomorphize synthetic enum {enum_name} without error_types")

        # Build variants from error_types
        from ast_nodes import EnumVariant
        variants = []
        for err_type in error_types:
            # Get variant name from the type
            if err_type.kind == TypeKind.STRUCT:
                variant_name = err_type.struct_name
            elif err_type.kind == TypeKind.ENUM:
                variant_name = err_type.enum_name
            else:
                variant_name = str(err_type)

            variants.append(EnumVariant(
                name=variant_name,
                associated_types=[("value", err_type)]
            ))

        self._register_concrete_enum(enum_name, variants)

    def _wrap_error_in_union(self, err_value, union_type: SawType, concrete_err_type: SawType):
        """Wrap an error value in the union enum type.

        Given an error value (e.g., ParseError), the union type (_CatchError_123),
        and the concrete error type as a structured SawType, creates an enum value
        with the appropriate variant.

        The variant is selected from the structured `concrete_err_type` (its
        struct/enum name), never by parsing a mangled name.
        """
        # Get the variant name from the structured error type. Union variants are
        # created in _ensure_enum_monomorphized keyed by struct_name/enum_name.
        if concrete_err_type is None:
            err_type_name = "Unknown"
        elif concrete_err_type.kind == TypeKind.STRUCT:
            err_type_name = concrete_err_type.struct_name
        elif concrete_err_type.kind == TypeKind.ENUM:
            err_type_name = concrete_err_type.enum_name
        else:
            err_type_name = str(concrete_err_type)

        return self._build_enum_case_value(err_value, union_type, err_type_name,
                                           what="union")

    def _build_enum_case_value(self, value, enum_type: SawType, case_name: str,
                               what: str = "enum"):
        """Build `<enum_type>.<case_name>(value)` — a one-payload enum case.

        Two callers, one construction: the multi-error catch's synthesized union
        (`_wrap_error_in_union`, which picks the case by the concrete error's
        NAME) and design 234 §3's routing clause (`_generate_try_propagate`,
        which takes the case the author wrote).
        """
        enum_name = enum_type.enum_name
        if enum_name not in self.enum_types:
            # Ensure it's monomorphized
            self._ensure_enum_monomorphized(enum_name, enum_type)

        llvm_enum_type, variant_tags, variant_info = self.enum_types[enum_name]

        if case_name not in variant_tags:
            raise ValueError(
                f"case {case_name} not found in {what} {enum_name}")

        enum_val = ir.Constant(llvm_enum_type, ir.Undefined)

        # Set the tag
        tag = ir.Constant(ir.IntType(32), variant_tags[case_name])
        enum_val = self.builder.insert_value(enum_val, tag, 0)

        # Create payload struct for the variant
        variant_params = variant_info[case_name]
        param_types = [self._get_llvm_type(t) for _, t in variant_params]
        param_struct_type = ir.LiteralStructType(param_types)

        param_struct = ir.Constant(param_struct_type, ir.Undefined)
        param_struct = self.builder.insert_value(param_struct, value, 0)

        # Convert struct to bytes and store in payload. Size the scratch to the
        # FULL payload `[N x i8]`, not the smaller variant struct — see
        # _create_result_err_for_return (design 94: the load reads all N bytes).
        payload_type = llvm_enum_type.elements[1]
        payload_alloca = self._entry_alloca(payload_type, name="union_err_alloca", align=8)
        struct_ptr = self.builder.bitcast(payload_alloca, ir.PointerType(param_struct_type))
        self.builder.store(param_struct, struct_ptr)

        payload_bytes = self.builder.load(payload_alloca, name="union_err_bytes")

        enum_val = self.builder.insert_value(enum_val, payload_bytes, 1)
        return enum_val

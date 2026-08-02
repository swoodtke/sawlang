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
        annotated = getattr(expr, 'result_enum_type', None)
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
        self._emit_panic(f"panic: try! failed at line {expr.line}")

        # OK block - extract value
        self.builder.position_at_end(ok_bb)
        return self._extract_result_ok_value(result_val, result_enum_name)

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

        # Check if we have an enclosing catch block
        catch_ctx = getattr(self, '_catch_context', None)
        if catch_ctx:
            # Unpack context - may have 2 or 4 elements depending on version
            if len(catch_ctx) == 4:
                catch_bb, err_alloca_ptr, error_type, error_types = catch_ctx
            else:
                catch_bb, err_alloca_ptr = catch_ctx
                error_type, error_types = None, []

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
            self.builder.branch(catch_bb)
        else:
            # No enclosing catch - propagate to caller. Erased Result (design
            # 56): if the enclosing function returns `Result<_, Box<any Trait>>`
            # and this callee's error is concrete, erase it into a fresh box at
            # the propagation edge (re-box). A callee already returning the box
            # passes straight through (no re-box) — no erase_propagate is set.
            erase = getattr(expr, 'erase_propagate', None)
            if erase is not None:
                err_value = self._erase_value_to_box(
                    err_value, erase['concrete'], erase['trait'], erase['allocator'])
            caller_result = self._create_result_err_for_return(err_value)
            self._cleanup_all_scopes()
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

        self.builder.branch(merge_bb)
        catch_end_bb = self.builder.block

        # Merge
        self.builder.position_at_end(merge_bb)
        phi = self.builder.phi(ok_value.type, name="try_catch_result")
        phi.add_incoming(ok_value, ok_end_bb)
        if catch_result is not None:
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
        error_type = getattr(expr, 'error_type', None)
        error_types = getattr(expr, 'error_types', [])
        is_union = len(error_types) > 1

        # If union type, ensure it's monomorphized so we have the LLVM type
        if is_union and error_type and error_type.enum_name:
            self._ensure_enum_monomorphized(error_type.enum_name, error_type, error_types)

        # Use a mutable list so try expressions can set the alloca when they know the error type
        # Also pass error type info for union wrapping
        err_alloca_ptr = [None]  # Will be set by first try expression that fails

        # Save old catch context and set new one
        # Context: (catch_bb, err_alloca_ptr, error_type, error_types)
        old_catch_ctx = getattr(self, '_catch_context', None)
        self._catch_context = (catch_bb, err_alloca_ptr, error_type, error_types)

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

        # Make error available as 'error' variable (if any try expression set it up)
        if err_alloca_ptr[0] is not None:
            old_error = self.variables.get("error")
            self.variables["error"] = err_alloca_ptr[0]

            # Generate catch block code
            catch_result = self._generate_block(expr.catch_block)
            catch_end_bb = self.builder.block

            # Restore old 'error' if any
            if old_error is not None:
                self.variables["error"] = old_error
            elif "error" in self.variables:
                del self.variables["error"]
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
        inside `resume` (whose own return type is `__Poll`, not the Result), so
        the wrap node's stored `result_type` is the authority there (design 92)."""
        # Prefer current_return_type — during generic monomorphization it is the
        # SUBSTITUTED concrete Result (the wrap node still carries the generic
        # template). Fall back to the node's type only when current_return_type is
        # not a Result: the coroutine-transform resume case, where `return` was
        # rewritten to a result-slot store and current_return_type is `__Poll`.
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

        # Convert struct to bytes and store in payload
        payload_type = llvm_enum_type.elements[1]
        payload_alloca = self._entry_alloca(param_struct_type, name="err_struct_alloca")
        self.builder.store(param_struct, payload_alloca)

        bytes_ptr = self.builder.bitcast(payload_alloca, ir.PointerType(payload_type))
        payload_bytes = self.builder.load(bytes_ptr, name="err_bytes")

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

        # Convert struct to bytes and store in payload
        payload_type = llvm_enum_type.elements[1]
        payload_alloca = self._entry_alloca(param_struct_type, name="ok_struct_alloca")
        self.builder.store(param_struct, payload_alloca)

        bytes_ptr = self.builder.bitcast(payload_alloca, ir.PointerType(payload_type))
        payload_bytes = self.builder.load(bytes_ptr, name="ok_bytes")

        result_val = self.builder.insert_value(result_val, payload_bytes, 1)
        return result_val

    def visit_ResultOkWrap(self, expr: ResultOkWrap):
        """Generate code for ResultOkWrap (T -> Result<T, E> as Ok).

        This is inserted by the typechecker when a value of type T
        is returned from a function with return type Result<T, E>.

        Design 40 item 5 (L10): the inner value escapes into the Ok payload —
        this is a transfer site. Generate it through _gen_transfer_value so an
        owned ImplicitCopy value (`return s` where `s: String`) is retained
        exactly as a direct return would retain it. Without the retain, scope
        cleanup releases the local and frees the buffer the payload still points
        at (premature free). `return move s` still works: the MoveExpr inside is
        not retained and the local is marked moved so cleanup skips it.
        """
        # design 92: a value-less Ok (bare `return` in a `Result<Void, E>`
        # function) has no inner expression to transfer — the Ok is the tag alone.
        rtype = getattr(expr, 'result_type', None)
        if expr.value is None:
            return self._create_result_ok_for_return(None, rtype)
        value = self._gen_transfer_value(expr.value)
        return self._create_result_ok_for_return(value, rtype)

    def visit_ResultErrWrap(self, expr: ResultErrWrap):
        """Generate code for ResultErrWrap (E -> Result<T, E> as Err).

        This is inserted by the typechecker when a value of type E
        is returned from a function with return type Result<T, E>.

        The Err payload is a transfer site too (design 40 item 5): retain an
        owned ImplicitCopy error value so scope cleanup does not free it early.
        """
        value = self._gen_transfer_value(expr.value)
        return self._create_result_err_for_return(value, getattr(expr, 'result_type', None))

    def visit_ErasedErrWrap(self, expr):
        """Generate code for ErasedErrWrap (design 56): erase a concrete `E`
        into a `Box<any Trait>` (through the allocator, Global by default), then
        build the Err payload from the fat pointer."""
        value = self._gen_transfer_value(expr.value)
        alloc_saw = expr.allocator or SawType(TypeKind.STRUCT, struct_name="GlobalAllocator")
        fat = self._erase_value_to_box(value, expr.concrete_err,
                                       expr.trait_name, alloc_saw)
        return self._create_result_err_for_return(fat)

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

        # Get the union enum type info
        union_enum_name = union_type.enum_name
        if union_enum_name not in self.enum_types:
            # Ensure it's monomorphized
            self._ensure_enum_monomorphized(union_enum_name, union_type)

        llvm_enum_type, variant_tags, variant_info = self.enum_types[union_enum_name]

        # Find the variant for this error type
        if err_type_name not in variant_tags:
            raise ValueError(f"Error type {err_type_name} not found in union {union_enum_name}")

        # Create the union enum value
        union_val = ir.Constant(llvm_enum_type, ir.Undefined)

        # Set the tag
        tag = ir.Constant(ir.IntType(32), variant_tags[err_type_name])
        union_val = self.builder.insert_value(union_val, tag, 0)

        # Create payload struct for the variant
        variant_params = variant_info[err_type_name]
        param_types = [self._get_llvm_type(t) for _, t in variant_params]
        param_struct_type = ir.LiteralStructType(param_types)

        param_struct = ir.Constant(param_struct_type, ir.Undefined)
        param_struct = self.builder.insert_value(param_struct, err_value, 0)

        # Convert struct to bytes and store in payload
        payload_type = llvm_enum_type.elements[1]
        payload_alloca = self._entry_alloca(param_struct_type, name="union_err_alloca")
        self.builder.store(param_struct, payload_alloca)

        bytes_ptr = self.builder.bitcast(payload_alloca, ir.PointerType(payload_type))
        payload_bytes = self.builder.load(bytes_ptr, name="union_err_bytes")

        union_val = self.builder.insert_value(union_val, payload_bytes, 1)
        return union_val

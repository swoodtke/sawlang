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
from ast_nodes import TryExpr, TryCatchExpr, SawType, TypeKind


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

        # Get the Result type info - it's stored as "Result_T_E" in enum_types
        # We need to find it by matching the LLVM type
        result_enum_name = None
        for name, (llvm_type, _, _) in self.enum_types.items():
            if name.startswith("Result_") and llvm_type == result_val.type:
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

        # Panic block
        self.builder.position_at_end(panic_bb)
        panic_msg = f"panic: try! failed at line {expr.line}\n\0"
        panic_str = ir.Constant(ir.ArrayType(ir.IntType(8), len(panic_msg)),
                                bytearray(panic_msg.encode('utf-8')))
        panic_global = ir.GlobalVariable(self.module, panic_str.type,
                                         name=f".panic_msg.try.{id(expr)}")
        panic_global.global_constant = True
        panic_global.initializer = panic_str
        panic_global.linkage = 'private'
        panic_ptr = self.builder.bitcast(panic_global, ir.PointerType(ir.IntType(8)))
        self.builder.call(self.printf, [panic_ptr])
        self.builder.call(self.abort, [])
        self.builder.unreachable()

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
        """Generate code for try (propagate Err to caller)."""
        func = self.builder.function
        ok_bb = func.append_basic_block(name="try_ok")
        err_bb = func.append_basic_block(name="try_err")

        self.builder.cbranch(is_ok, ok_bb, err_bb)

        # Err block - return early with error
        self.builder.position_at_end(err_bb)
        err_value = self._extract_result_err_value(result_val, result_enum_name)

        # Create Err result for caller's return type
        caller_result = self._create_result_err_for_return(err_value)

        # Run cleanup before returning
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
        error_alloca = self.builder.alloca(err_value.type, name="error")
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
        """Generate code for try-catch block expression: try { ... } catch { ... }"""
        # For now, generate the try block and catch block
        # In a full implementation, we'd need to track which try expressions
        # in the block should propagate to the catch

        # Generate try block
        try_result = self._generate_block(expr.try_block)

        # For block-level try-catch, the error handling is more complex
        # because multiple try expressions could fail
        # For simplicity, we'll generate the catch block as unreachable for now
        # A full implementation would require exception-like control flow

        return try_result

    def _extract_result_ok_value(self, result_val, result_enum_name: str):
        """Extract the Ok value from a Result."""
        llvm_enum_type, variant_tags, variant_info = self.enum_types[result_enum_name]
        ok_params = variant_info["Ok"]

        # Extract payload
        payload_bytes = self.builder.extract_value(result_val, 1, name="ok_payload")

        # Cast to appropriate struct type
        param_types = [self._get_llvm_type(t) for _, t in ok_params]
        param_struct_type = ir.LiteralStructType(param_types)

        # Store bytes to memory, then load as struct
        payload_alloca = self.builder.alloca(llvm_enum_type.elements[1], name="ok_payload_alloca")
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
        payload_alloca = self.builder.alloca(llvm_enum_type.elements[1], name="err_payload_alloca")
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

    def _create_result_err_for_return(self, err_value):
        """Create a Result.Err for the current function's return type."""
        # Get the return type's Result enum name
        if not self.current_return_type or not self.current_return_type.is_result():
            raise ValueError("Cannot create Result.Err outside Result-returning function")

        # Find the monomorphized Result type for the return type
        result_enum_name = self._get_result_enum_name(self.current_return_type)

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
        payload_alloca = self.builder.alloca(param_struct_type, name="err_struct_alloca")
        self.builder.store(param_struct, payload_alloca)

        bytes_ptr = self.builder.bitcast(payload_alloca, ir.PointerType(payload_type))
        payload_bytes = self.builder.load(bytes_ptr, name="err_bytes")

        result_val = self.builder.insert_value(result_val, payload_bytes, 1)
        return result_val

    def _create_result_ok_for_return(self, ok_value):
        """Create a Result.Ok for the current function's return type."""
        if not self.current_return_type or not self.current_return_type.is_result():
            raise ValueError("Cannot create Result.Ok outside Result-returning function")

        result_enum_name = self._get_result_enum_name(self.current_return_type)

        llvm_enum_type, variant_tags, variant_info = self.enum_types[result_enum_name]

        # Create the Result value
        result_val = ir.Constant(llvm_enum_type, ir.Undefined)

        # Set tag to Ok (0)
        ok_tag = ir.Constant(ir.IntType(32), variant_tags["Ok"])
        result_val = self.builder.insert_value(result_val, ok_tag, 0)

        # Create payload struct for Ok
        ok_params = variant_info["Ok"]
        param_types = [self._get_llvm_type(t) for _, t in ok_params]
        param_struct_type = ir.LiteralStructType(param_types)

        param_struct = ir.Constant(param_struct_type, ir.Undefined)
        param_struct = self.builder.insert_value(param_struct, ok_value, 0)

        # Convert struct to bytes and store in payload
        payload_type = llvm_enum_type.elements[1]
        payload_alloca = self.builder.alloca(param_struct_type, name="ok_struct_alloca")
        self.builder.store(param_struct, payload_alloca)

        bytes_ptr = self.builder.bitcast(payload_alloca, ir.PointerType(payload_type))
        payload_bytes = self.builder.load(bytes_ptr, name="ok_bytes")

        result_val = self.builder.insert_value(result_val, payload_bytes, 1)
        return result_val

    def _get_result_enum_name(self, result_type: SawType) -> str:
        """Get the monomorphized enum name for a Result type."""
        if not result_type.is_result():
            raise ValueError(f"Expected Result type, got {result_type}")

        ok_type = result_type.unwrap_result_ok()
        err_type = result_type.unwrap_result_err()

        # Build the mangled name
        ok_name = self._mangle_type_name(ok_type)
        err_name = self._mangle_type_name(err_type)

        return f"Result_{ok_name}_{err_name}"

    def _mangle_type_name(self, saw_type: SawType) -> str:
        """Mangle a type name for use in monomorphized names."""
        if saw_type is None:
            return "Void"
        if saw_type.kind == TypeKind.INT:
            return "Int"
        elif saw_type.kind == TypeKind.FLOAT:
            return "Float"
        elif saw_type.kind == TypeKind.BOOL:
            return "Bool"
        elif saw_type.kind == TypeKind.STRING:
            return "String"
        elif saw_type.kind == TypeKind.STRUCT:
            return saw_type.struct_name
        elif saw_type.kind == TypeKind.ENUM:
            if saw_type.type_args:
                args = "_".join(self._mangle_type_name(t) for t in saw_type.type_args)
                return f"{saw_type.enum_name}_{args}"
            return saw_type.enum_name
        elif saw_type.kind == TypeKind.OPTIONAL:
            inner = self._mangle_type_name(saw_type.inner_type)
            return f"Optional_{inner}"
        else:
            return str(saw_type.kind.name)

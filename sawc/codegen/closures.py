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
from ast_nodes import ClosureExpr


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
        # Determine closure parameter and return types
        param_types = []
        param_names = []

        if expr.parameters:
            for param in expr.parameters:
                if param.type_annotation:
                    param_types.append(self._get_llvm_type(param.type_annotation))
                else:
                    # Type should have been inferred by typechecker
                    # For now, use Int as fallback
                    param_types.append(ir.IntType(64))
                param_names.append(param.name)
        elif expr.shorthand_param_count > 0:
            # Shorthand params - types should be inferred
            for i in range(expr.shorthand_param_count):
                param_types.append(ir.IntType(64))  # Fallback type
                param_names.append(f"${i}")

        # Get return type from body (we'll determine during generation)
        # For now, assume Int or Void based on whether body has final_expr
        if expr.body.final_expr:
            ret_type = ir.IntType(64)  # Default return type
        else:
            ret_type = ir.VoidType()

        # Create environment struct type for captures
        env_ptr_type = ir.PointerType(ir.IntType(8))
        captures = expr.captures or []

        if captures:
            # Build environment struct with captured variables
            env_field_types = []
            for cap_name in captures:
                if cap_name in self.variable_types:
                    cap_type = self._get_llvm_type(self.variable_types[cap_name])
                elif cap_name in self.variables:
                    # Get type from the alloca
                    alloca = self.variables[cap_name]
                    cap_type = alloca.type.pointee
                else:
                    cap_type = ir.IntType(64)  # Fallback
                env_field_types.append(cap_type)
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

        # Save current builder and variables
        saved_builder = self.builder
        saved_variables = self.variables.copy()
        saved_variable_types = self.variable_types.copy()
        saved_cleanup_stack = self.cleanup_stack[:]

        # Generate closure body
        entry = closure_fn.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(entry)
        self.variables = {}
        self.variable_types = {}
        self.cleanup_stack = []

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
                    [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), i)],
                    name=f"cap_{cap_name}_ptr"
                )
                # Load the captured value
                cap_value = self.builder.load(field_ptr, name=f"cap_{cap_name}")
                # Store in a local alloca so it can be used like a variable
                alloca = self._entry_alloca(cap_value.type, name=cap_name)
                self.builder.store(cap_value, alloca)
                self.variables[cap_name] = alloca

        # Set up parameter access
        for i, param_name in enumerate(param_names):
            llvm_param = closure_fn.args[i + 1]  # +1 for env_ptr
            alloca = self._entry_alloca(param_types[i], name=param_name)
            self.builder.store(llvm_param, alloca)
            self.variables[param_name] = alloca

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
                    self.builder.ret(ir.Constant(ret_type, 0))

        # Restore context
        self.builder = saved_builder
        self.variables = saved_variables
        self.variable_types = saved_variable_types
        self.cleanup_stack = saved_cleanup_stack

        # Create environment struct on stack and copy captured values
        if captures and env_struct_type:
            env_alloca = self._entry_alloca(env_struct_type, name="closure_env")
            for i, cap_name in enumerate(captures):
                if cap_name in self.variables:
                    cap_value = self.builder.load(self.variables[cap_name], name=f"load_{cap_name}")
                    field_ptr = self.builder.gep(
                        env_alloca,
                        [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), i)],
                        name=f"env_field_{i}"
                    )
                    self.builder.store(cap_value, field_ptr)
            env_ptr_val = self.builder.bitcast(env_alloca, env_ptr_type, name="env_ptr")
        else:
            env_ptr_val = ir.Constant(env_ptr_type, None)

        # Create closure struct: { fn_ptr, env_ptr }
        closure_type = ir.LiteralStructType([ir.PointerType(fn_type), env_ptr_type])
        closure_val = ir.Constant(closure_type, ir.Undefined)
        closure_val = self.builder.insert_value(closure_val, closure_fn, 0, name="closure_fn")
        closure_val = self.builder.insert_value(closure_val, env_ptr_val, 1, name="closure_env")

        return closure_val

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

"""
Method and function generation for the Saw code generator.

This module provides mixin methods for generating LLVM IR code for functions,
methods (instance, static, init), and extension methods.

Usage:
    class CodeGenerator(MethodsMixin, ...):
        pass
"""

from llvmlite import ir
from ast_nodes import (
    Function, Block, Method, Extension, SawType, TypeKind
)


class MethodsMixin:
    """Mixin providing method and function generation for CodeGenerator.

    Methods:
        _generate_extension_methods: Generate all methods in an extension
        _generate_method: Generate a single instance method
        _generate_field_deinit_calls: Generate deinit calls for struct fields
        _generate_init_method: Generate a custom init method
        _generate_static_method: Generate a static method
        _generate_function: Generate a function body
        _generate_block: Generate a block of statements
    """

    def _generate_extension_methods(self, extension: Extension):
        """Generate code for all methods in an extension."""
        # Skip generic extensions - they'll be monomorphized when the struct is used
        if extension.type_params:
            return

        # Set Self type context for this extension
        old_self_context = self.self_type_context
        self.self_type_context = extension.struct_name

        for method in extension.methods:
            if method.is_init:
                self._generate_init_method(extension.struct_name, method)
            elif method.is_static:
                self._generate_static_method(extension.struct_name, method)
            else:
                self._generate_method(extension.struct_name, method)

        # Restore Self type context
        self.self_type_context = old_self_context

    def _generate_method(self, struct_name: str, method: Method):
        """Generate code for a single instance method."""
        mangled_name = self._mangle_method_name(struct_name, method.name)
        llvm_func = self.functions[mangled_name]

        # Create entry block
        block = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(block)

        # Clear variables and cleanup stack for this method
        self.variables = {}
        self.variable_types = {}
        self.cleanup_stack = []

        # Determine the Self type for this extension
        if struct_name == "String":
            self_llvm_type = ir.IntType(8).as_pointer()  # String is i8*
            self_saw_type = SawType(TypeKind.STRING)
        else:
            self_llvm_type = self.struct_types[struct_name][0]
            self_saw_type = SawType(TypeKind.STRUCT, struct_name=struct_name)

        # Create allocas for parameters (including self)
        for i, param in enumerate(method.parameters):
            llvm_func.args[i].name = param.name
            # For mutable self, it's already a pointer - just store it directly
            if i == 0 and param.name == "self" and method.self_mutable:
                self.variables[param.name] = llvm_func.args[i]
                self.variable_types[param.name] = self_saw_type
            elif param.name == "self":
                # Handle 'self' parameter - use the Self type
                alloca = self.builder.alloca(self_llvm_type, name=param.name)
                self.builder.store(llvm_func.args[i], alloca)
                self.variables[param.name] = alloca
                self.variable_types[param.name] = self_saw_type
            else:
                alloca = self.builder.alloca(self._get_llvm_type(param.type), name=param.name)
                self.builder.store(llvm_func.args[i], alloca)
                self.variables[param.name] = alloca
                self.variable_types[param.name] = param.type

        # Set current return type for implicit optional wrapping
        old_return_type = self.current_return_type
        self.current_return_type = method.return_type

        # Generate method body
        result = self._generate_block(method.body)

        # For deinit methods, auto-call deinit on fields that implement Deinit
        if method.name == "deinit" and not self.builder.block.is_terminated:
            self._generate_field_deinit_calls(struct_name)

        # Handle return
        if method.return_type.kind == TypeKind.VOID:
            if not self.builder.block.is_terminated:
                self.builder.ret_void()
        else:
            if not self.builder.block.is_terminated:
                if result is not None:
                    self.builder.ret(result)
                else:
                    # Return default value
                    default = ir.Constant(self._get_llvm_type(method.return_type), 0)
                    self.builder.ret(default)

        # Restore return type
        self.current_return_type = old_return_type

    def _generate_field_deinit_calls(self, struct_name: str):
        """Generate deinit calls for all fields that implement Deinit.

        Called at the end of a deinit method to ensure nested resources are cleaned up.
        Fields are cleaned up in reverse declaration order.
        """
        # Use namespace for struct field types
        field_types = self.namespace.get_struct_fields(struct_name)
        if not field_types:
            return
        _, field_order = self.struct_types[struct_name]

        # Get self pointer
        self_ptr = self.variables.get("self")
        if self_ptr is None:
            return

        # Process fields in reverse order
        for field_name in reversed(field_order):
            field_type = field_types.get(field_name)
            if field_type is None:
                continue

            # Check if this field type needs deinit
            behavior = self._get_cleanup_behavior(field_type)
            if behavior == "none":
                continue

            # Get the field's type name for method lookup
            type_name = self._get_type_name_for_conformance(field_type)
            if type_name is None:
                continue

            # Check if deinit method exists
            deinit_method_name = self._mangle_method_name(type_name, "deinit")
            if deinit_method_name not in self.functions:
                continue

            deinit_fn = self.functions[deinit_method_name]

            # Get pointer to field
            field_index = field_order.index(field_name)
            field_ptr = self.builder.gep(self_ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), field_index)
            ], name=f"{field_name}_ptr")

            # Call deinit on the field (deinit takes var self = pointer)
            self.builder.call(deinit_fn, [field_ptr])

    def _generate_init_method(self, struct_name: str, method: Method):
        """Generate code for a custom init method."""
        param_names = [p.name for p in method.parameters]
        mangled_name = self._mangle_method_name(struct_name, method.name, param_names)
        llvm_func = self.functions[mangled_name]

        # Create entry block
        block = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(block)

        # Clear variables and cleanup stack for this method
        self.variables = {}
        self.variable_types = {}
        self.cleanup_stack = []

        # Set current return type for None literal generation
        old_return_type = self.current_return_type
        self.current_return_type = method.return_type

        # Create allocas for parameters (no self for init methods)
        for i, param in enumerate(method.parameters):
            llvm_func.args[i].name = param.name
            alloca = self.builder.alloca(self._get_llvm_type(param.type), name=param.name)
            self.builder.store(llvm_func.args[i], alloca)
            self.variables[param.name] = alloca
            self.variable_types[param.name] = param.type

        # Generate method body - must return a struct value
        result = self._generate_block(method.body)

        # Handle return - init methods must return the struct
        if not self.builder.block.is_terminated:
            if result is not None:
                self.builder.ret(result)
            else:
                # Error: init must return a struct
                # For now, return a default struct value
                struct_type, _ = self.struct_types[struct_name]
                default = ir.Constant(struct_type, ir.Undefined)
                self.builder.ret(default)

        # Restore previous return type
        self.current_return_type = old_return_type

    def _generate_static_method(self, struct_name: str, method: Method):
        """Generate code for a static method (no self parameter)."""
        mangled_name = self._mangle_method_name(struct_name, method.name)
        llvm_func = self.functions[mangled_name]

        # Create entry block
        block = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(block)

        # Clear variables and cleanup stack for this method
        self.variables = {}
        self.variable_types = {}
        self.cleanup_stack = []

        # Set current return type for None literal generation
        old_return_type = self.current_return_type
        self.current_return_type = method.return_type

        # Create allocas for parameters (no self for static methods)
        for i, param in enumerate(method.parameters):
            llvm_func.args[i].name = param.name
            alloca = self.builder.alloca(self._get_llvm_type(param.type), name=param.name)
            self.builder.store(llvm_func.args[i], alloca)
            self.variables[param.name] = alloca
            self.variable_types[param.name] = param.type

        # Generate method body
        result = self._generate_block(method.body)

        # Handle return
        if not self.builder.block.is_terminated:
            if method.return_type.kind == TypeKind.VOID:
                self.builder.ret_void()
            elif result is not None:
                self.builder.ret(result)
            else:
                self.builder.ret_void()

        # Restore previous return type
        self.current_return_type = old_return_type

    def _generate_function(self, func: Function, name_override: str = None):
        """Generate a function body. If name_override is provided, use it instead of func.name."""
        func_name = name_override if name_override else func.name
        llvm_func = self.functions[func_name]

        # Create entry block
        block = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(block)

        # Clear variables and cleanup stack for this function
        self.variables = {}
        self.variable_types = {}
        self.cleanup_stack = []

        # Set current return type for None literal generation
        old_return_type = self.current_return_type
        self.current_return_type = func.return_type

        # Create allocas for parameters and track for cleanup
        # Push a scope for function parameters (cleaned up when function returns)
        self.cleanup_stack.append([])
        for i, param in enumerate(func.parameters):
            llvm_func.args[i].name = param.name
            alloca = self.builder.alloca(self._get_llvm_type(param.type), name=param.name)
            self.builder.store(llvm_func.args[i], alloca)
            self.variables[param.name] = alloca
            self.variable_types[param.name] = param.type
            # Track parameter for cleanup if it needs it
            if self._needs_cleanup(param.type):
                self.cleanup_stack[-1].append((param.name, param.type))

        # Generate function body (block manages its own cleanup scope)
        result = self._generate_block(func.body)

        # Handle return - cleanup parameter scope before returning
        if func.return_type.kind == TypeKind.VOID:
            if not self.builder.block.is_terminated:
                # Cleanup parameter scope before return
                self._cleanup_all_scopes()
                # For main(), return 0 instead of void
                if func.name == "main":
                    self.builder.ret(ir.Constant(ir.IntType(32), 0))
                else:
                    self.builder.ret_void()
        else:
            if not self.builder.block.is_terminated:
                # Cleanup parameter scope before return
                self._cleanup_all_scopes()
                if result is not None:
                    self.builder.ret(result)
                else:
                    # Return default value
                    default = ir.Constant(self._get_llvm_type(func.return_type), 0)
                    self.builder.ret(default)

        # Restore previous return type
        self.current_return_type = old_return_type

    def _generate_block(self, block: Block, manage_cleanup: bool = True):
        """Generate code for a block.

        Args:
            block: The block to generate code for
            manage_cleanup: If True, push/pop a cleanup scope for this block.
                          Set to False when the caller manages cleanup (e.g., functions).
        """
        # Push new cleanup scope for this block
        if manage_cleanup:
            self.cleanup_stack.append([])

        result = None

        for stmt in block.statements:
            self._generate_statement(stmt)
            if self.builder.block.is_terminated:
                # Early exit (return/break) already handled cleanup
                if manage_cleanup:
                    self.cleanup_stack.pop()
                return None

        if block.final_expr is not None:
            # Honor a CustomCopy `needs_copy` annotation on a tail-return final
            # expression (only the function/method body's final_expr is marked
            # by the value-transfer checkpoint, so other blocks are unaffected).
            result = self._gen_transfer_value(block.final_expr)

        # Cleanup variables declared in this block
        if manage_cleanup:
            scope_vars = self.cleanup_stack.pop()
            if not self.builder.block.is_terminated:
                self._cleanup_scope(scope_vars)

        return result

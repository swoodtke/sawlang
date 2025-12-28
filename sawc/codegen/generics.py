"""
Generic type handling for the Saw code generator.

This module provides mixin methods for monomorphization of generic functions,
structs, enums, and extensions. Generics in Saw are implemented via
monomorphization - creating specialized versions of generic code for each
concrete type instantiation.

Usage:
    class CodeGenerator(GenericsMixin, ...):
        pass
"""

from typing import Optional, List
from llvmlite import ir
from ast_nodes import (
    SawType, TypeKind, Extension, EnumVariant, Method
)


class GenericsMixin:
    """Mixin providing generics/monomorphization methods for CodeGenerator.

    Methods:
        _mangle_generic_name: Generate mangled name for generic function instantiation
        _instantiate_generic_function: Instantiate a generic function with concrete types
        _mangle_method_name: Generate mangled name for methods
        _mangle_generic_struct_name: Generate mangled name for generic struct instantiation
        _substitute_saw_type: Substitute type parameters with concrete types
        _ensure_monomorphized_struct: Ensure monomorphized struct version exists
        _ensure_monomorphized_enum: Ensure monomorphized enum version exists
        _monomorphize_extension: Generate monomorphized extension methods
        _monomorphize_single_extension: Generate single extension's monomorphized methods
        _generate_method_generic: Generate method code with type substitution
        _generate_init_method_generic: Generate init method code with type substitution
    """

    def _mangle_generic_name(self, func_name: str, type_args: List[SawType]) -> str:
        """Generate mangled name for generic instantiation: identity$Int or swap$Int_String"""
        type_names = []
        for t in type_args:
            type_names.append(self._type_to_string(t))
        return f"{func_name}${'_'.join(type_names)}"

    def _instantiate_generic_function(self, func_name: str, type_args: List[SawType]) -> str:
        """Instantiate a generic function with concrete type arguments.

        Returns the mangled name of the instantiated function.
        """
        if func_name not in self.generic_functions:
            raise ValueError(f"Unknown generic function: {func_name}")

        mangled_name = self._mangle_generic_name(func_name, type_args)

        # Check if already instantiated
        if mangled_name in self.generated_instantiations:
            return mangled_name

        # Get the generic function template
        generic_func = self.generic_functions[func_name]

        # Set up type parameter context
        if len(type_args) != len(generic_func.type_params):
            raise ValueError(
                f"Generic function {func_name} expects {len(generic_func.type_params)} "
                f"type arguments, got {len(type_args)}"
            )

        # Save current state (we might be in the middle of generating another function)
        saved_builder = self.builder
        saved_variables = self.variables.copy()
        saved_variable_types = self.variable_types.copy()
        saved_cleanup_stack = self.cleanup_stack[:]
        old_context = self.type_param_context.copy()

        # Build type parameter mapping
        for type_param, type_arg in zip(generic_func.type_params, type_args):
            self.type_param_context[type_param.name] = type_arg

            # Add associated type mappings for interface bounds
            for bound in type_param.bounds:
                # Get the concrete type name
                concrete_type_name = None
                if type_arg.kind == TypeKind.STRUCT:
                    concrete_type_name = type_arg.struct_name
                elif type_arg.kind == TypeKind.ENUM:
                    concrete_type_name = type_arg.enum_name

                if concrete_type_name:
                    # Get the associated type assignments for this (type, interface) pair (use namespace)
                    if concrete_type_name in self.namespace.conformances:
                        type_assigns = self.namespace.conformances[concrete_type_name].get(bound, {})
                        for assoc_name, assoc_type in type_assigns.items():
                            self.type_param_context[assoc_name] = assoc_type

        try:
            # Declare the instantiated function
            self._declare_function(generic_func, name_override=mangled_name)

            # Generate the function body
            self._generate_function(generic_func, name_override=mangled_name)

            # Mark as generated
            self.generated_instantiations.add(mangled_name)
        finally:
            # Restore state
            self.type_param_context = old_context
            self.builder = saved_builder
            self.variables = saved_variables
            self.variable_types = saved_variable_types
            self.cleanup_stack = saved_cleanup_stack

        return mangled_name

    def _mangle_method_name(self, struct_name: str, method_name: str, param_names: Optional[List[str]] = None) -> str:
        """Generate mangled name for methods: StructName_methodName
           For init methods, include parameter names to allow overloading."""
        if param_names is not None:
            # Init method - include parameter signature
            param_sig = '_'.join(param_names)
            return f"{struct_name}_{method_name}_{param_sig}"
        else:
            return f"{struct_name}_{method_name}"

    def _mangle_generic_struct_name(self, base_name: str, type_args: List[SawType]) -> str:
        """Generate mangled name for generic struct instantiation: Box<Int> -> Box_Int"""
        def type_to_string(t: SawType) -> str:
            if t.kind == TypeKind.INT:
                return "Int"
            elif t.kind == TypeKind.FLOAT:
                return "Float"
            elif t.kind == TypeKind.BOOL:
                return "Bool"
            elif t.kind == TypeKind.STRING:
                return "String"
            elif t.kind == TypeKind.STRUCT:
                if t.type_args:
                    return self._mangle_generic_struct_name(t.struct_name, t.type_args)
                return t.struct_name
            elif t.kind == TypeKind.ENUM:
                if t.type_args:
                    return self._mangle_generic_struct_name(t.enum_name, t.type_args)
                return t.enum_name
            elif t.kind == TypeKind.OPTIONAL:
                return f"Optional_{type_to_string(t.inner_type)}"
            elif t.kind == TypeKind.TUPLE:
                inner = "_".join(type_to_string(elem) for elem in t.element_types)
                return f"Tuple_{inner}"
            else:
                return str(t.kind.name)

        args_str = "_".join(type_to_string(t) for t in type_args)
        return f"{base_name}_{args_str}"

    def _substitute_saw_type(self, saw_type: SawType, type_mapping: dict[str, SawType]) -> SawType:
        """Substitute type parameters with concrete types in a SawType."""
        if saw_type.kind == TypeKind.TYPE_PARAM:
            if saw_type.type_param_name in type_mapping:
                return type_mapping[saw_type.type_param_name]
            return saw_type
        elif saw_type.kind == TypeKind.OPTIONAL:
            if saw_type.inner_type:
                new_inner = self._substitute_saw_type(saw_type.inner_type, type_mapping)
                return SawType(TypeKind.OPTIONAL, inner_type=new_inner)
            return saw_type
        elif saw_type.kind == TypeKind.POINTER:
            if saw_type.inner_type:
                new_inner = self._substitute_saw_type(saw_type.inner_type, type_mapping)
                return SawType(TypeKind.POINTER, inner_type=new_inner, pointer_mutable=saw_type.pointer_mutable)
            return saw_type
        elif saw_type.kind == TypeKind.TUPLE:
            if saw_type.element_types:
                new_elements = [self._substitute_saw_type(e, type_mapping) for e in saw_type.element_types]
                return SawType(TypeKind.TUPLE, element_types=new_elements)
            return saw_type
        elif saw_type.kind == TypeKind.STRUCT:
            # Check if this is actually a type parameter (parsed as STRUCT)
            if saw_type.struct_name in type_mapping:
                return type_mapping[saw_type.struct_name]
            if saw_type.type_args:
                new_type_args = [self._substitute_saw_type(t, type_mapping) for t in saw_type.type_args]
                return SawType(TypeKind.STRUCT, struct_name=saw_type.struct_name, type_args=new_type_args)
            return saw_type
        elif saw_type.kind == TypeKind.ENUM:
            if saw_type.type_args:
                new_type_args = [self._substitute_saw_type(t, type_mapping) for t in saw_type.type_args]
                return SawType(TypeKind.ENUM, enum_name=saw_type.enum_name, type_args=new_type_args)
            return saw_type
        else:
            return saw_type

    def _ensure_monomorphized_struct(self, struct_name: str, type_args: List[SawType]) -> str:
        """Ensure a monomorphized version of a generic struct exists.
        Returns the mangled name of the monomorphized struct."""
        mangled_name = self._mangle_generic_struct_name(struct_name, type_args)

        # Already generated
        if mangled_name in self.struct_types:
            return mangled_name

        # Get the generic struct
        if struct_name not in self.generic_structs:
            raise ValueError(f"Unknown generic struct: {struct_name}")
        generic_struct = self.generic_structs[struct_name]

        # Build type mapping: T -> Int, etc.
        type_mapping = {}
        for i, type_param in enumerate(generic_struct.type_params):
            if i < len(type_args):
                type_mapping[type_param.name] = type_args[i]

        # Set type param context for _get_llvm_type
        old_context = self.type_param_context
        self.type_param_context = type_mapping

        # Generate field types with substitution
        field_types = []
        for field in generic_struct.fields:
            substituted = self._substitute_saw_type(field.type, type_mapping)
            field_types.append(self._get_llvm_type(substituted))

        # Create identified struct type (unique identity even if same field types)
        llvm_struct_type = self.module.context.get_identified_type(mangled_name)
        llvm_struct_type.set_body(*field_types)

        # Store the type and field order
        field_order = [field.name for field in generic_struct.fields]
        self.struct_types[mangled_name] = (llvm_struct_type, field_order)

        # Restore context before generating extensions
        # (extensions will set their own context)
        self.type_param_context = old_context

        # If there's a generic extension for this struct, also monomorphize its methods
        if struct_name in self.generic_extensions:
            self._monomorphize_extension(struct_name, type_args, mangled_name, type_mapping)

        return mangled_name

    def _ensure_monomorphized_enum(self, enum_name: str, type_args: List[SawType]) -> str:
        """Ensure a monomorphized version of a generic enum exists.
        Returns the mangled name of the monomorphized enum."""
        mangled_name = self._mangle_generic_struct_name(enum_name, type_args)

        # Already generated
        if mangled_name in self.enum_types:
            return mangled_name

        # Get the generic enum
        if enum_name not in self.generic_enums:
            raise ValueError(f"Unknown generic enum: {enum_name}")
        generic_enum = self.generic_enums[enum_name]

        # Build type mapping: T -> Int, etc.
        type_mapping = {}
        for i, type_param in enumerate(generic_enum.type_params):
            if i < len(type_args):
                type_mapping[type_param.name] = type_args[i]

        # Set type param context for _get_llvm_type
        old_context = self.type_param_context
        self.type_param_context = type_mapping

        # Create substituted variants
        substituted_variants = []
        for variant in generic_enum.variants:
            substituted_types = []
            for param_name, param_type in variant.associated_types:
                substituted = self._substitute_saw_type(param_type, type_mapping)
                substituted_types.append((param_name, substituted))
            substituted_variants.append(EnumVariant(
                name=variant.name,
                associated_types=substituted_types
            ))

        # Restore context before registering (registration will use _get_llvm_type)
        self.type_param_context = old_context

        # Register the monomorphized enum
        self._register_concrete_enum(mangled_name, substituted_variants)

        return mangled_name

    def _monomorphize_extension(self, struct_name: str, type_args: List[SawType],
                                 mangled_struct_name: str, type_mapping: dict[str, SawType]):
        """Generate monomorphized version of extension methods for a generic struct."""
        # Process all extensions for this struct
        for generic_ext in self.generic_extensions[struct_name]:
            self._monomorphize_single_extension(generic_ext, type_args, mangled_struct_name, type_mapping)

    def _monomorphize_single_extension(self, generic_ext: Extension, type_args: List[SawType],
                                        mangled_struct_name: str, type_mapping: dict[str, SawType]):
        """Generate monomorphized version of a single extension's methods."""

        # Save current state - we may be in the middle of generating another function
        saved_builder = self.builder
        saved_variables = self.variables
        saved_variable_types = self.variable_types.copy() if self.variable_types else {}
        saved_cleanup_stack = self.cleanup_stack[:] if self.cleanup_stack else []

        # Set type param context
        old_context = self.type_param_context
        self.type_param_context = type_mapping

        # First pass: register all methods (so methods can call each other)
        methods_to_generate = []
        for method in generic_ext.methods:
            # Create mangled name using the monomorphized struct name
            if method.is_init:
                param_names = [p.name for p in method.parameters]
                mangled_name = self._mangle_method_name(mangled_struct_name, method.name, param_names)
            else:
                mangled_name = self._mangle_method_name(mangled_struct_name, method.name)

            # Build parameter types with substitution
            if method.is_init:
                param_types = []
                for p in method.parameters:
                    substituted = self._substitute_saw_type(p.type, type_mapping)
                    param_types.append(self._get_llvm_type(substituted))
                struct_type, _ = self.struct_types[mangled_struct_name]
                return_type = struct_type
            else:
                param_types = []
                for i, p in enumerate(method.parameters):
                    if i == 0 and p.name == "self":
                        # Self type is the monomorphized struct
                        llvm_type = self.struct_types[mangled_struct_name][0]
                    else:
                        substituted = self._substitute_saw_type(p.type, type_mapping)
                        llvm_type = self._get_llvm_type(substituted)
                    if i == 0 and p.name == "self" and method.self_mutable:
                        llvm_type = llvm_type.as_pointer()
                    param_types.append(llvm_type)
                substituted_return = self._substitute_saw_type(method.return_type, type_mapping)
                return_type = self._get_llvm_type(substituted_return)

            # Create function type and register
            func_type = ir.FunctionType(return_type, param_types)
            llvm_func = ir.Function(self.module, func_type, name=mangled_name)
            self.functions[mangled_name] = llvm_func
            methods_to_generate.append(method)

        # Second pass: generate method bodies
        for method in methods_to_generate:
            if method.is_init:
                self._generate_init_method_generic(mangled_struct_name, method, type_mapping)
            else:
                self._generate_method_generic(mangled_struct_name, method, type_mapping)

        # Restore all state
        self.type_param_context = old_context
        self.builder = saved_builder
        self.variables = saved_variables
        self.variable_types = saved_variable_types
        self.cleanup_stack = saved_cleanup_stack

    def _generate_method_generic(self, struct_name: str, method: Method, type_mapping: dict[str, SawType]):
        """Generate code for a method with type substitution."""
        mangled_name = self._mangle_method_name(struct_name, method.name)
        llvm_func = self.functions[mangled_name]

        # Create entry block
        block = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(block)

        # Clear variables for this method
        self.variables = {}

        # Set type param context for method body
        old_context = self.type_param_context
        self.type_param_context = type_mapping

        # Create allocas for parameters (including self)
        for i, param in enumerate(method.parameters):
            llvm_func.args[i].name = param.name
            if i == 0 and param.name == "self" and method.self_mutable:
                self.variables[param.name] = llvm_func.args[i]
            else:
                if i == 0 and param.name == "self":
                    param_type = self.struct_types[struct_name][0]
                else:
                    substituted = self._substitute_saw_type(param.type, type_mapping)
                    param_type = self._get_llvm_type(substituted)
                alloca = self.builder.alloca(param_type, name=param.name)
                self.builder.store(llvm_func.args[i], alloca)
                self.variables[param.name] = alloca

        # Generate method body
        result = self._generate_block(method.body)

        # Handle return
        substituted_return = self._substitute_saw_type(method.return_type, type_mapping)
        if substituted_return.kind == TypeKind.VOID:
            if not self.builder.block.is_terminated:
                self.builder.ret_void()
        else:
            if not self.builder.block.is_terminated:
                if result is not None:
                    self.builder.ret(result)
                else:
                    return_type = self._get_llvm_type(substituted_return)
                    self.builder.ret(ir.Constant(return_type, ir.Undefined))

        # Restore context
        self.type_param_context = old_context

    def _generate_init_method_generic(self, struct_name: str, method: Method, type_mapping: dict[str, SawType]):
        """Generate code for an init method with type substitution."""
        param_names = [p.name for p in method.parameters]
        mangled_name = self._mangle_method_name(struct_name, method.name, param_names)
        llvm_func = self.functions[mangled_name]

        # Create entry block
        block = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(block)

        # Clear variables for this method
        self.variables = {}

        # Set type param context
        old_context = self.type_param_context
        self.type_param_context = type_mapping

        # Create allocas for parameters
        for i, param in enumerate(method.parameters):
            llvm_func.args[i].name = param.name
            substituted = self._substitute_saw_type(param.type, type_mapping)
            param_type = self._get_llvm_type(substituted)
            alloca = self.builder.alloca(param_type, name=param.name)
            self.builder.store(llvm_func.args[i], alloca)
            self.variables[param.name] = alloca

        # Generate init body
        result = self._generate_block(method.body)

        # Return the result (should be a struct)
        if not self.builder.block.is_terminated:
            if result is not None:
                self.builder.ret(result)
            else:
                struct_type, _ = self.struct_types[struct_name]
                self.builder.ret(ir.Constant(struct_type, ir.Undefined))

        # Restore context
        self.type_param_context = old_context

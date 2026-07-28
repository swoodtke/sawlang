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
from .mangle import mangle_function, mangle_named, mangle_method


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
        """Generate mangled name for a generic function instantiation.

        Delegates to the canonical mangler (see codegen/mangle.py).
        """
        return mangle_function(func_name, type_args)

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
        """Generate mangled name for a method or init.

        Delegates to the canonical mangler (see codegen/mangle.py).
        """
        return mangle_method(struct_name, method_name, param_names)

    def _mangle_generic_struct_name(self, base_name: str, type_args: List[SawType]) -> str:
        """Generate mangled name for a generic struct/enum monomorphization.

        Delegates to the canonical mangler (see codegen/mangle.py). Both the
        producer that registers the specialized type and every consumer that
        looks it up route through this one function, guaranteeing symmetry.
        """
        return mangle_named(base_name, type_args)

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
        # Check if there's a specialized extension for this exact type
        spec_key = self._make_specialization_key(type_args)
        full_key = (struct_name, spec_key)

        # Collect method names from specialized extensions (these override generic ones)
        specialized_method_names = set()
        if full_key in self.specialized_extensions:
            for spec_ext in self.specialized_extensions[full_key]:
                for method in spec_ext.methods:
                    specialized_method_names.add(method.name)

        # Process generic extensions, skipping methods that have specialized overrides
        if struct_name in self.generic_extensions:
            for generic_ext in self.generic_extensions[struct_name]:
                # Conditional conformance: an extension declared with type-param
                # bounds (e.g. `extension Vector<T: Copy>`) only exists for
                # instantiations that satisfy those bounds. When a bound is
                # unmet (e.g. Vector<File> — File is not Copy), its methods are
                # simply not instantiated, so merely constructing the type no
                # longer drags in an uninstantiable `copy()` body. A later call
                # to the missing method is diagnosed by the typechecker.
                if not self._extension_bounds_satisfied(generic_ext, type_args):
                    continue
                self._monomorphize_single_extension(
                    generic_ext, type_args, mangled_struct_name, type_mapping,
                    skip_methods=specialized_method_names
                )

        # Process specialized extensions (no skipping, no type substitution needed)
        if full_key in self.specialized_extensions:
            for spec_ext in self.specialized_extensions[full_key]:
                self._monomorphize_single_extension(spec_ext, type_args, mangled_struct_name, {})

    def _extension_bounds_satisfied(self, generic_ext: Extension,
                                    type_args: List[SawType]) -> bool:
        """Whether the concrete `type_args` satisfy an extension's declared
        type-param bounds.

        The extension's type params (`extension Vector<T: Copy>` -> [T: Copy])
        line up positionally with the struct's type params, which is the same
        order as `type_args`. Bound satisfaction is decided by the shared
        namespace helper so it matches the typechecker exactly (`Copy` is
        structural; any other trait is a conformance lookup).
        """
        for i, tp in enumerate(generic_ext.type_params):
            if not tp.bounds or i >= len(type_args):
                continue
            concrete = type_args[i]
            for bound in tp.bounds:
                if not self.namespace.type_satisfies_bound(concrete, bound):
                    return False
        return True

    def _make_specialization_key(self, type_args: List[SawType]) -> tuple:
        """Convert type arguments to a specialization key tuple."""
        key_parts = []
        for t in type_args:
            if t.kind == TypeKind.STRING:
                key_parts.append("String")
            elif t.kind == TypeKind.INT:
                key_parts.append("Int")
            elif t.kind == TypeKind.UINT:
                key_parts.append("UInt")
            elif t.kind == TypeKind.FLOAT:
                key_parts.append("Float")
            elif t.kind == TypeKind.BOOL:
                key_parts.append("Bool")
            elif t.kind == TypeKind.INT8:
                key_parts.append("Int8")
            elif t.kind == TypeKind.INT16:
                key_parts.append("Int16")
            elif t.kind == TypeKind.INT32:
                key_parts.append("Int32")
            elif t.kind == TypeKind.INT64:
                key_parts.append("Int64")
            elif t.kind == TypeKind.UINT8:
                key_parts.append("UInt8")
            elif t.kind == TypeKind.UINT16:
                key_parts.append("UInt16")
            elif t.kind == TypeKind.UINT32:
                key_parts.append("UInt32")
            elif t.kind == TypeKind.UINT64:
                key_parts.append("UInt64")
            elif t.kind == TypeKind.STRUCT and t.struct_name:
                key_parts.append(t.struct_name)
            else:
                # Can't create key for this type
                return ()
        return tuple(key_parts)

    def _monomorphize_single_extension(self, generic_ext: Extension, type_args: List[SawType],
                                        mangled_struct_name: str, type_mapping: dict[str, SawType],
                                        skip_methods: set = None):
        """Generate monomorphized version of a single extension's methods.

        Args:
            skip_methods: Set of method names to skip (because specialized versions exist)
        """
        if skip_methods is None:
            skip_methods = set()

        # Set type param context
        old_context = self.type_param_context
        self.type_param_context = type_mapping

        # First pass: register all methods (so methods can call each other)
        methods_to_generate = []
        for method in generic_ext.methods:
            # Skip methods that have specialized overrides
            if method.name in skip_methods:
                continue
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
            # Mark &var params (and a &var self receiver) noalias; see
            # _mark_noalias_params / _declare_extension_methods.
            self._mark_noalias_params(llvm_func, [p.type for p in method.parameters])
            if (not method.is_init and not method.is_static
                    and getattr(method, 'self_mutable', False)):
                llvm_func.args[0].add_attribute('noalias')
            methods_to_generate.append(method)

        # Second pass: queue method bodies for later generation
        # This ensures all method signatures are declared before any bodies are generated
        for method in methods_to_generate:
            self.pending_method_bodies.append((mangled_struct_name, method, type_mapping.copy(), method.is_init))

        # Restore type param context (other state will be set up when generating bodies)
        self.type_param_context = old_context

    def _generate_pending_method_bodies(self):
        """Generate all pending monomorphized method bodies.

        This is called after all method signatures have been declared,
        ensuring that method calls within bodies can find their targets.
        """
        while self.pending_method_bodies:
            mangled_struct_name, method, type_mapping, is_init = self.pending_method_bodies.pop(0)

            # Set up type param context for this method
            old_context = self.type_param_context
            self.type_param_context = type_mapping

            if is_init:
                self._generate_init_method_generic(mangled_struct_name, method, type_mapping)
            else:
                self._generate_method_generic(mangled_struct_name, method, type_mapping)

            self.type_param_context = old_context

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
                alloca = self._entry_alloca(param_type, name=param.name)
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
            alloca = self._entry_alloca(param_type, name=param.name)
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

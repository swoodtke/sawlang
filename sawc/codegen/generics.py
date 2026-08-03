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
        saved_drop_flags = self.drop_flags
        saved_moved_variables = self.moved_variables
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
            self.drop_flags = saved_drop_flags
            self.moved_variables = saved_moved_variables

        return mangled_name

    def _mangle_method_name(self, struct_name: str, method_name: str,
                            param_names: Optional[List[str]] = None,
                            method_type_args: Optional[List[SawType]] = None) -> str:
        """Generate mangled name for a method or init.

        Delegates to the canonical mangler (see codegen/mangle.py). For a
        generic method (`func map<U>(...)`), `method_type_args` composes the
        method's own type arguments into the symbol (brief 36).
        """
        return mangle_method(struct_name, method_name, param_names, method_type_args)

    def _fill_default_type_args(self, base_name: str, type_args: List[SawType]) -> List[SawType]:
        """Design 37 — append declared defaults for omitted trailing type args,
        the codegen twin of the typechecker's identity rule.

        The typechecker canonicalizes most types to their fully-applied form,
        but codegen also derives struct identities from raw AST annotations and
        substituted field/return types, so it must fill here too. This is the
        chokepoint: because every mangling and monomorphization of a named type
        funnels through the functions that call this, `Vector<Int>` and
        `Vector<Int, Global>` produce ONE mangled name and ONE monomorphized
        struct — the miscompile-class dual-identity hazard is closed. Idempotent:
        already-full argument lists pass through unchanged.
        """
        decl = self.generic_structs.get(base_name) or self.generic_enums.get(base_name)
        params = getattr(decl, 'type_params', None) if decl is not None else None
        if not params or len(type_args) >= len(params):
            return type_args
        filled = list(type_args)
        for i in range(len(type_args), len(params)):
            default = getattr(params[i], 'default', None)
            if default is None:
                break
            filled.append(self._substitute_saw_type(default, self.type_param_context))
        return filled

    def _mangle_generic_struct_name(self, base_name: str, type_args: List[SawType]) -> str:
        """Generate mangled name for a generic struct/enum monomorphization.

        Delegates to the canonical mangler (see codegen/mangle.py). Both the
        producer that registers the specialized type and every consumer that
        looks it up route through this one function, guaranteeing symmetry.
        Default type args are filled first (design 37) so an under-applied
        `Vector<Int>` mangles identically to the explicit `Vector<Int, Global>`.
        """
        type_args = self._fill_default_type_args(base_name, type_args)
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

    def _canonicalize_type_kind(self, saw_type: SawType) -> SawType:
        """Re-tag a type whose *kind* was left STRUCT but whose name actually
        denotes an ENUM (design 61, L14).

        A named type written in source (`Slot`, `MapSlot<K, V>`) is parsed as a
        STRUCT-kinded `SawType` because the parser cannot know it is an enum. The
        typechecker's `_resolve_type` rewrites such annotations to ENUM, but it
        does NOT recurse through POINTER/ARRAY inner types, so a concrete type
        argument that reaches codegen as a monomorphization binding (e.g. the `T`
        of `Vector<Slot>`) can still be STRUCT-kinded. That wrong tag flows into
        the monomorphization CONTEXT and then, via `_expr_type`, into the
        drop-glue kind switch (`_emit_drop_at`), which selects struct field
        cleanup instead of enum tag-switch cleanup — so owning enum payloads
        (Map/Set slots, any `Vector<enum>`) never run their deinit.

        Fixing the tag HERE — at the point the monomorphized binding is recorded
        — keeps the enum an enum through every downstream site (container deinit,
        remove/overwrite/grow) uniformly, rather than point-patching one cleanup
        path. Mangling is kind-agnostic for named types (`mangle_named` keys on
        the bare name), so this never splits or renames a monomorphization.
        """
        if saw_type is None:
            return saw_type
        kind = saw_type.kind
        # An erased `Box<any Trait>` (design 51) never monomorphizes through
        # box.saw — its layout is a fat pointer and its teardown is vtable-driven
        # (arity-agnostic: `_emit_erased_box_drop` defaults a missing allocator to
        # Global). Codegen's native canonical form is the arity-1 `Box<any Trait>`
        # (the as-written annotation): every container/enum that embeds it is
        # registered and torn down through this chokepoint at arity-1, so its
        # element-drop lookups stay stable. The typechecker, however, canonicalizes
        # `Box<any Trait>` to arity-2 `Box<any Trait, Global>` on expression types,
        # so a `match`/`try` that mangles a typechecker-stamped `Result<T,
        # Box<any Error>>` directly would look up the arity-2 name and mangle-miss
        # the arity-1-registered enum — then the LLVM-type fallback silently selects
        # a same-sized WRONG monomorphization (design 68, DF6(b)/DF9(c)). Normalize
        # every erased box DOWN to the codegen-native arity-1 here (dropping a
        # redundant trailing `Global`, the only default this wrapper has) so the
        # match/try lookups — routed through this same canonicalizer — agree with
        # registration. A non-default allocator arg is preserved.
        if self._is_erased_box(saw_type):
            targs = saw_type.type_args
            if (len(targs) == 2 and targs[1].kind == TypeKind.STRUCT
                    and targs[1].struct_name == "GlobalAllocator"
                    and not targs[1].type_args):
                return SawType(TypeKind.STRUCT, struct_name=saw_type.struct_name,
                               type_args=[targs[0]], symbol=saw_type.symbol)
            return saw_type
        if kind == TypeKind.STRUCT and saw_type.struct_name:
            name = saw_type.struct_name
            args = ([self._canonicalize_type_kind(a) for a in saw_type.type_args]
                    if saw_type.type_args else saw_type.type_args)
            # Fill omitted trailing defaults (design 37) so the canonical identity
            # matches the monomorphized one — e.g. an annotation `Map<Int, R>`
            # becomes `Map<Int, R, Global>`, so its deinit lookup resolves.
            if args:
                args = self._fill_default_type_args(name, args)
            if name in self.generic_enums or name in self.enum_types:
                return SawType(TypeKind.ENUM, enum_name=name, type_args=args,
                               symbol=saw_type.symbol)
            if args is not saw_type.type_args:
                return SawType(TypeKind.STRUCT, struct_name=name, type_args=args,
                               symbol=saw_type.symbol)
            return saw_type
        if kind == TypeKind.ENUM and saw_type.type_args:
            args = [self._canonicalize_type_kind(a) for a in saw_type.type_args]
            args = self._fill_default_type_args(saw_type.enum_name, args)
            return SawType(TypeKind.ENUM, enum_name=saw_type.enum_name,
                           type_args=args, symbol=saw_type.symbol)
        if kind == TypeKind.OPTIONAL and saw_type.inner_type:
            return SawType(TypeKind.OPTIONAL,
                           inner_type=self._canonicalize_type_kind(saw_type.inner_type))
        if kind == TypeKind.POINTER and saw_type.inner_type:
            return SawType(TypeKind.POINTER,
                           inner_type=self._canonicalize_type_kind(saw_type.inner_type),
                           pointer_mutable=saw_type.pointer_mutable)
        if kind == TypeKind.REFERENCE and saw_type.inner_type:
            return SawType(TypeKind.REFERENCE,
                           inner_type=self._canonicalize_type_kind(saw_type.inner_type),
                           reference_mutable=saw_type.reference_mutable)
        if kind == TypeKind.TUPLE and saw_type.element_types:
            return SawType(TypeKind.TUPLE,
                           element_types=[self._canonicalize_type_kind(e)
                                          for e in saw_type.element_types])
        if kind == TypeKind.ARRAY and saw_type.array_element_type:
            return SawType(TypeKind.ARRAY,
                           array_element_type=self._canonicalize_type_kind(saw_type.array_element_type),
                           array_size=saw_type.array_size)
        return saw_type

    def _mark_stored_closure_escaping(self, saw_type: SawType) -> SawType:
        """Mark a function TYPE bound to a container's type parameter as escaping
        (design 77 item 3).

        A closure stored in a container (a Vector/Map/Set element, an Optional/
        tuple/array payload of one) is an OWNING value: its refcounted env must be
        retained on copy and released at teardown. The typechecker stamps the
        escaping bit on such stored positions, but it is not part of the mangling,
        so a type arg reconstructed from a mangled monomorphization key arrives
        with the bit cleared — and then `_needs_cleanup`/the Copy-bound predicate
        (which gate on `func_is_escaping`) treat the element as non-owning: the env
        leaks and copies are unbalanced. Restore the bit for the STORED positions.
        A function type in a genuine parameter role never reaches here (it lives in
        a method signature, not a container type argument). Returns a fresh SawType
        so no shared instance is mutated.
        """
        if saw_type is None:
            return saw_type
        k = saw_type.kind
        if k == TypeKind.FUNCTION and not saw_type.func_is_escaping:
            return SawType(TypeKind.FUNCTION, param_types=saw_type.param_types,
                           func_return_type=saw_type.func_return_type,
                           func_is_sync=saw_type.func_is_sync,
                           func_is_escaping=True)
        if k == TypeKind.OPTIONAL and saw_type.inner_type is not None:
            return SawType(TypeKind.OPTIONAL,
                           inner_type=self._mark_stored_closure_escaping(saw_type.inner_type))
        if k == TypeKind.ARRAY and saw_type.array_element_type is not None:
            return SawType(TypeKind.ARRAY,
                           array_element_type=self._mark_stored_closure_escaping(saw_type.array_element_type),
                           array_size=saw_type.array_size)
        if k == TypeKind.TUPLE and saw_type.element_types:
            return SawType(TypeKind.TUPLE,
                           element_types=[self._mark_stored_closure_escaping(e)
                                          for e in saw_type.element_types])
        return saw_type

    def _ensure_monomorphized_struct(self, struct_name: str, type_args: List[SawType]) -> str:
        """Ensure a monomorphized version of a generic struct exists.
        Returns the mangled name of the monomorphized struct."""
        # Design 37: fill omitted trailing type args from defaults BEFORE building
        # the type mapping, so `Vector<Int>` binds A=Global (not leaving A
        # unbound) and produces the same struct identity as `Vector<Int, Global>`.
        type_args = self._fill_default_type_args(struct_name, type_args)
        # design 61 (L14): re-tag any STRUCT-kinded arg that is really an enum so
        # the binding stored in the monomorphization context carries kind ENUM,
        # and enum drop glue is selected for owning enum-payload elements. Kind is
        # not part of the mangling, so identity is unchanged.
        type_args = [self._canonicalize_type_kind(a) for a in type_args]
        # A function TYPE bound to a container's type param is a STORED (escaping)
        # closure: it lives in the buffer, so its env must be retained on copy and
        # released at teardown. The escaping bit is not part of the mangling and
        # is lost when a type arg is reconstructed from a mangled name, so restore
        # it here (design 77 item 3) — else `_needs_cleanup`/copy-bound treat the
        # element as non-owning and the env leaks / is not retained.
        type_args = [self._mark_stored_closure_escaping(a) for a in type_args]
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
        # Record base name + concrete args so a monomorphized deinit can rebuild
        # its receiver's SawType for appended field cleanup (allocator leak fix).
        self.mono_struct_args[mangled_name] = (struct_name, list(type_args))

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
        # Design 37: fill omitted trailing type args from defaults (identity rule).
        type_args = self._fill_default_type_args(enum_name, type_args)
        # design 61 (L14): re-tag STRUCT-kinded args that are really enums (e.g.
        # a `MapSlot<K, V>` payload type) so nested enum drop glue is selected.
        type_args = [self._canonicalize_type_kind(a) for a in type_args]
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
            # Method-level GENERIC methods (`func map<U>(...)`, brief 36) are NOT
            # monomorphized at struct-instantiation time: their own type params
            # (U) are only known at the call site, so they are specialized
            # per (struct args, method args) pair on demand via
            # _ensure_monomorphized_generic_method. Skip them here.
            if getattr(method, 'type_params', None):
                continue
            self._declare_monomorphized_method(mangled_struct_name, method, type_mapping)
            methods_to_generate.append(method)

        # Second pass: queue method bodies for later generation
        # This ensures all method signatures are declared before any bodies are generated
        for method in methods_to_generate:
            self.pending_method_bodies.append((mangled_struct_name, method, type_mapping.copy(), method.is_init))

        # Restore type param context (other state will be set up when generating bodies)
        self.type_param_context = old_context

    def _mono_self_llvm_type(self, struct_name: str):
        """The LLVM type of a `self` receiver for a monomorphized method.

        A plain/generic struct's self is its (possibly monomorphized) struct
        type; `String`'s self is `i8*` (design 40 item 9 — String has no entry
        in struct_types, matching the eager `_generate_method` path)."""
        prim = self._primitive_self_llvm_type(struct_name)
        if prim is not None:
            return prim
        return self.struct_types[struct_name][0]

    def _declare_monomorphized_method(self, mangled_struct_name: str, method: Method,
                                      type_mapping: dict[str, SawType]) -> str:
        """Declare the LLVM signature for one monomorphized method; return its
        mangled symbol.

        Shared by struct-time extension monomorphization and the per-call-site
        generic-method path (brief 36). `type_mapping` carries the FULL binding:
        the struct's type params plus, for a generic method, its own type params.
        Idempotent — a signature already declared is returned as-is.
        """
        # Method-level type args (brief 36): reconstruct from the mapping so the
        # symbol composes struct specialization x method type args. Empty for an
        # ordinary (non-generic) method, giving the unchanged `Struct_method`.
        method_type_args = ([type_mapping[tp.name] for tp in method.type_params]
                            if getattr(method, 'type_params', None) else None)
        if method.is_init:
            param_names = [p.name for p in method.parameters]
            mangled_name = self._mangle_method_name(mangled_struct_name, method.name, param_names)
        else:
            mangled_name = self._mangle_method_name(mangled_struct_name, method.name,
                                                    method_type_args=method_type_args)
        if mangled_name in self.functions:
            return mangled_name

        old_context = self.type_param_context
        self.type_param_context = type_mapping
        try:
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
                        # Self type is the monomorphized struct — or i8* for a
                        # generic method on `extension String` (C6).
                        llvm_type = self._mono_self_llvm_type(mangled_struct_name)
                    else:
                        substituted = self._substitute_saw_type(p.type, type_mapping)
                        llvm_type = self._get_llvm_type(substituted)
                    if i == 0 and p.name == "self" and method.self_mutable:
                        llvm_type = llvm_type.as_pointer()
                    param_types.append(llvm_type)
                substituted_return = self._substitute_saw_type(method.return_type, type_mapping)
                return_type = self._get_llvm_type(substituted_return)

            func_type = ir.FunctionType(return_type, param_types)
            llvm_func = ir.Function(self.module, func_type, name=mangled_name)
            self.functions[mangled_name] = llvm_func
            # Mark &var params (and a &var self receiver) noalias; see
            # _mark_noalias_params / _declare_extension_methods.
            self._mark_noalias_params(llvm_func, [p.type for p in method.parameters])
            if (not method.is_init and not method.is_static
                    and getattr(method, 'self_mutable', False)):
                llvm_func.args[0].add_attribute('noalias')
            # Design 108: register default parameter values under this mono's
            # mangled name (the non-generic _declare_method path does this, but a
            # per-call-site generic-method instantiation routes only through here).
            # Without it, an omitted trailing default on a generic method
            # (`x.f<Int>(1)` for `func f<T>(&self, a, b: T = 0)`) is never filled
            # and the call is emitted with too few args (an llvmlite ICE).
            defaults = [p.default_value for p in method.parameters]
            if any(d is not None for d in defaults):
                self.method_defaults[mangled_name] = defaults
        finally:
            self.type_param_context = old_context
        return mangled_name

    def _ensure_monomorphized_generic_method(self, mangled_struct_name: str,
                                             recv_type: SawType, method_name: str,
                                             method_type_args: List[SawType]) -> str:
        """Ensure a generic method (`func map<U>(...)`) is specialized for this
        (struct args, method args) pair, and return its mangled symbol (brief 36).

        Called at the call site, where the method's own type args are finally
        known. Declares the signature synchronously (so the call can look it up)
        and queues the body on the existing pending-body queue, which is drained
        after all signatures exist — the same two-phase discipline the struct-time
        path uses, so a generic method may call other (generic or not) methods.
        """
        # For a non-generic receiver type (a plain struct or String) the SawType
        # carries no struct_name (STRING) or has no type args; fall back to the
        # mangled name as the lookup key (design 40 item 9).
        base_name = recv_type.struct_name or mangled_struct_name
        struct_type_args = recv_type.type_args or []

        mangled_name = self._mangle_method_name(mangled_struct_name, method_name,
                                                method_type_args=method_type_args)
        if mangled_name in self.functions:
            return mangled_name

        # Locate the generic method AST across the struct's generic extensions.
        method = None
        for generic_ext in self.generic_extensions.get(base_name, []):
            for m in generic_ext.methods:
                if m.name == method_name and getattr(m, 'type_params', None):
                    method = m
                    break
            if method is not None:
                break
        # Design 40 item 9 (C6): a generic method on a NON-generic-type extension
        # lives in plain_generic_methods, keyed by the receiver's name.
        if method is None:
            method = (self.plain_generic_methods.get(base_name, {}).get(method_name)
                      or self.plain_generic_methods.get(mangled_struct_name, {}).get(method_name))
        if method is None:
            raise ValueError(
                f"Unknown generic method {base_name}.{method_name}"
            )

        # Build the FULL binding: struct type params, then the method's own.
        type_mapping: dict[str, SawType] = {}
        generic_struct = self.generic_structs.get(base_name)
        if generic_struct is not None:
            for i, tp in enumerate(generic_struct.type_params):
                if i < len(struct_type_args):
                    type_mapping[tp.name] = struct_type_args[i]
        for tp, ta in zip(method.type_params, method_type_args):
            type_mapping[tp.name] = ta

        self._declare_monomorphized_method(mangled_struct_name, method, type_mapping)
        self.pending_method_bodies.append(
            (mangled_struct_name, method, type_mapping.copy(), method.is_init))
        return mangled_name

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
        # Recompose the method's own type args from the binding so a generic
        # method's body is looked up under the same composed symbol its signature
        # was declared with (brief 36); empty for an ordinary method.
        method_type_args = ([type_mapping[tp.name] for tp in method.type_params]
                            if getattr(method, 'type_params', None) else None)
        mangled_name = self._mangle_method_name(struct_name, method.name,
                                                method_type_args=method_type_args)
        llvm_func = self.functions[mangled_name]

        # Create entry block
        block = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(block)

        # design 69: attach the DISubprogram + prime the line location (mono body
        # maps to the ORIGINAL method's source lines).
        self._di_begin_function(llvm_func, f"{struct_name}.{method.name}",
                                getattr(method, 'source_file', ''),
                                getattr(method, 'line', 0))

        # Clear variables for this method. Isolate the cleanup state too:
        # drop-flag allocas (design 42) belong to THIS llvm function and must not
        # leak into another; save/restore so the caller's scopes are untouched.
        self.variables = {}
        saved_cleanup_stack = self.cleanup_stack
        saved_drop_flags = self.drop_flags
        saved_moved_variables = self.moved_variables
        self.cleanup_stack = []
        self.drop_flags = {}
        self.moved_variables = set()

        # Set type param context for method body
        old_context = self.type_param_context
        self.type_param_context = type_mapping

        # Set the (substituted) return type so return-position wrapping works
        # inside the monomorphized body: `None` literals learn their optional
        # inner type, and Result auto-wrap (`return T`/`return E` in a
        # Result-returning method, e.g. Vector.try_with_capacity) can build the
        # correct Ok/Err. Without this, current_return_type would leak in from
        # the enclosing generation context and misclassify the method.
        substituted_return = self._substitute_saw_type(method.return_type, type_mapping)
        old_return_type = self.current_return_type
        self.current_return_type = substituted_return

        # Param cleanup scope (design 42 + design 65). An owned by-value param —
        # whether of a static factory (`Box<T, A>.make_or`) OR an instance method
        # (`Map._hash_code`/`_key_eq`'s owning KEY) — that is NOT moved out on some
        # path must be RELEASED at scope exit rather than leaked. Each owning param
        # is registered with a drop flag; every recognized move (explicit `move`,
        # transfer into a construction, and now the placement-store `ptr[i]=value`
        # primitive — design 65 clears the flag there) clears the flag, so a moved
        # param is not double-freed. Before design 65 instance-method params were
        # excluded because the placement-move a `Vector.push` performs could not be
        # observed by a drop flag; now that it is, instance params are safe to
        # register — which is what stops the map's owning-key probe copies leaking.
        register_params = True
        if register_params:
            self.cleanup_stack.append([])

        # Create allocas for parameters (including self)
        for i, param in enumerate(method.parameters):
            llvm_func.args[i].name = param.name
            is_self = (i == 0 and param.name == "self")
            if is_self and method.self_mutable:
                self.variables[param.name] = llvm_func.args[i]
                continue
            if is_self:
                param_type = self._mono_self_llvm_type(struct_name)
                substituted = None
            else:
                substituted = self._substitute_saw_type(param.type, type_mapping)
                param_type = self._get_llvm_type(substituted)
            alloca = self._entry_alloca(param_type, name=param.name)
            self.builder.store(llvm_func.args[i], alloca)
            self.variables[param.name] = alloca
            if register_params and substituted is not None and self._needs_cleanup(substituted):
                self._register_cleanup(param.name, substituted)

        # Generate method body
        result = self._generate_block(method.body)

        # For a monomorphized `deinit`, append field cleanup exactly as the
        # non-generic path does (methods.py `_generate_field_deinit_calls`). A
        # user deinit body with owning by-value fields — e.g. Map/Set's backing
        # `Vector<..., A>` — relies on this to drop them; without it the backing
        # buffer leaks and never routes through the value's own allocator `A`.
        # The receiver's concrete SawType (base + args) is rebuilt so the field
        # types substitute `A` correctly and the right monomorphized field-deinit
        # is selected.
        if (method.name == "deinit"
                and not method.is_static
                and not self.builder.block.is_terminated):
            self_ptr = self.variables.get("self")
            base_args = self.mono_struct_args.get(struct_name)
            if self_ptr is not None and base_args is not None:
                base_name, targs = base_args
                self_saw = SawType(TypeKind.STRUCT, struct_name=base_name,
                                   type_args=list(targs))
                self._emit_field_cleanup_at(self_ptr, self_saw)

        # Handle return — for a static factory, clean the param scope on the
        # fall-through path (explicit `return`s inside already ran cleanup).
        if not self.builder.block.is_terminated:
            if register_params:
                self._cleanup_all_scopes()
            if substituted_return.kind == TypeKind.VOID:
                self.builder.ret_void()
            elif result is not None:
                self.builder.ret(self._coerce_ret_value(result))
            else:
                return_type = self._get_llvm_type(substituted_return)
                self.builder.ret(ir.Constant(return_type, ir.Undefined))

        # Restore context
        self.current_return_type = old_return_type
        self.type_param_context = old_context
        self.cleanup_stack = saved_cleanup_stack
        self.drop_flags = saved_drop_flags
        self.moved_variables = saved_moved_variables

    def _generate_init_method_generic(self, struct_name: str, method: Method, type_mapping: dict[str, SawType]):
        """Generate code for an init method with type substitution."""
        param_names = [p.name for p in method.parameters]
        mangled_name = self._mangle_method_name(struct_name, method.name, param_names)
        llvm_func = self.functions[mangled_name]

        # Create entry block
        block = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(block)

        # design 69: attach the DISubprogram + prime the line location.
        self._di_begin_function(llvm_func, f"{struct_name}.{method.name}",
                                getattr(method, 'source_file', ''),
                                getattr(method, 'line', 0))

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
                self.builder.ret(self._coerce_ret_value(result))
            else:
                struct_type, _ = self.struct_types[struct_name]
                self.builder.ret(ir.Constant(struct_type, ir.Undefined))

        # Restore context
        self.type_param_context = old_context

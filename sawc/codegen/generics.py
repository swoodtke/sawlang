"""
Generic type lowering for the Saw code generator.

Codegen decides no instantiations. The monomorphization phase
(`sawc/monomorphize.py`) walks the demand fixpoint, materializes every instance
through one funnel (the substituting copier, then the instance check with
errors real) and splices each one into the merged program as an ordinary
concrete declaration. A monomorphized method's body is emitted by
`_generate_method` / `_generate_init_method` / `_generate_static_method`, the
same generators a hand-written extension's methods go through, so an instance
gets the same param-cleanup registration, `variable_types` scope and ICE
breadcrumb. What lives here is the layout of a type instance, the mangling
both sides share, and lookups that raise an internal error on a miss
(design 218).

Usage:
    class CodeGenerator(GenericsMixin, ...):
        pass
"""

from typing import List
from llvmlite import ir
from ast_nodes import SawType, TypeKind, EnumVariant
from .mangle import mangle_function, mangle_named, mangle_method
from mono_identity import (
    CodegenIdentityEnv, canonicalize_type_kind, fill_default_type_args,
    instance_is_lowered_specially, mark_stored_closure_escaping,
)


class GenericsMixin:
    """Mixin providing generics/monomorphization methods for CodeGenerator.

    Methods:
        _mangle_generic_name: Generate mangled name for generic function instantiation
        _instantiate_generic_function: the symbol of a generic function's instance
        _mangle_method_name: Generate mangled name for methods
        _mangle_generic_struct_name: Generate mangled name for generic struct instantiation
        _substitute_saw_type: Substitute type parameters with concrete types
        _ensure_monomorphized_struct: Ensure monomorphized struct version exists
        _ensure_monomorphized_enum: Ensure monomorphized enum version exists
        _receiver_saw_type: the base+args type behind a mangled receiver name
        _register_registry_type_instances: every registry instance's layout, up front
        _ensure_monomorphized_generic_method: the symbol of a method instance
    """

    def _mangle_generic_name(self, func_name: str, type_args: List[SawType]) -> str:
        """Generate mangled name for a generic function instantiation.

        Delegates to the canonical mangler (see codegen/mangle.py).
        """
        return mangle_function(func_name, type_args)

    def _instantiate_generic_function(self, func_name: str,
                                      type_args: List[SawType]) -> str:
        """The mangled symbol of a generic free function's instantiation.

        A lookup, despite the name. The monomorphization phase decides which
        instances exist, materializes each one (`monomorphize.materialize_instance`)
        and splices it into the merged program as an ordinary concrete
        function, which the eager declaration pass has already declared by the
        time any body is generated.

        A miss is an internal error: the standing decides-vs-lowers gate. It
        means the fixpoint failed to enumerate a demand this lowering makes, so
        it names the pair rather than quietly building a body nothing checked.
        """
        mangled_name = self._mangle_generic_name(func_name, type_args)
        if mangled_name in self.functions:
            return mangled_name
        raise ValueError(
            f"internal compiler error: monomorphization did not discover the "
            f"instance `{mangled_name}` of generic function `{func_name}`, "
            f"demanded while lowering "
            f"{self._current_llvm_function_name() or '<registration>'}")

    def _current_llvm_function_name(self):
        """The LLVM function under construction, for an ICE report."""
        builder = getattr(self, 'builder', None)
        block = getattr(builder, 'block', None) if builder is not None else None
        return getattr(getattr(block, 'parent', None), 'name', None)

    def _mangle_method_name(self, struct_name: str, method_name: str,
                            param_names: Optional[List[str]] = None,
                            method_type_args: Optional[List[SawType]] = None) -> str:
        """Generate mangled name for a method or init.

        Delegates to the canonical mangler (see codegen/mangle.py). For a
        generic method (`func map<U>(...)`), `method_type_args` composes the
        method's own type arguments into the symbol (design 36).
        """
        return mangle_method(struct_name, method_name, param_names, method_type_args)

    # Every `_ensure_*` / `_instantiate_*` entry for a function or a method is
    # a lookup whose miss is an internal error. The two type entries below do
    # mint a layout on demand, by design: layouts are minted from the
    # registry's own set up front (`_register_registry_type_instances`), and
    # these are its lazy re-entry under a different demand path, not a second
    # opinion about which instances exist.

    @property
    def _identity_env(self):
        """This code generator, seen as a `mono_identity.IdentityEnv`.

        Built once and cached; it reads `generic_structs` / `generic_enums` /
        `enum_types` / `type_param_context` LIVE, so the cache is safe.
        """
        env = getattr(self, '_identity_env_cache', None)
        if env is None:
            env = CodegenIdentityEnv(self)
            self._identity_env_cache = env
        return env

    def _fill_default_type_args(self, base_name: str, type_args: List[SawType]) -> List[SawType]:
        """Append declared defaults for omitted trailing type args (design 37).

        The rule and its rationale live in `mono_identity`, which the
        monomorphization phase calls too, so codegen and that phase give one
        answer to "what is this instance". This method is a convenience for
        codegen's many call sites.
        """
        return fill_default_type_args(self._identity_env, base_name, type_args)

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
        elif saw_type.kind == TypeKind.ARRAY:
            # A `[T; N]` field of a generic struct (`struct FixedBuf<const N:
            # Int> { data: [UInt8; N] }`) needs both its element and its length
            # substituted before `_get_llvm_type` sees it. `_substituted_length`
            # does the length; the element needs this walker's `type_mapping`
            # (design 148).
            if saw_type.array_element_type is None:
                return saw_type
            new_elem = self._substitute_saw_type(saw_type.array_element_type,
                                                 type_mapping)
            size, size_expr = saw_type._substituted_length(type_mapping)
            return SawType(TypeKind.ARRAY, array_element_type=new_elem,
                           array_size=size, array_size_expr=size_expr)
        elif saw_type.kind == TypeKind.REFERENCE:
            if saw_type.inner_type:
                new_inner = self._substitute_saw_type(saw_type.inner_type, type_mapping)
                return SawType(TypeKind.REFERENCE, inner_type=new_inner,
                               reference_mutable=saw_type.reference_mutable)
            return saw_type
        else:
            return saw_type

    def _canonicalize_type_kind(self, saw_type: SawType) -> SawType:
        """Re-tag a STRUCT-kinded name that denotes an ENUM and normalize an
        erased box to arity 1 (design 51).

        Delegates to `mono_identity`, which the monomorphization phase calls
        too; see `_fill_default_type_args` for why the answer lives there.
        """
        return canonicalize_type_kind(self._identity_env, saw_type)

    def _mark_stored_closure_escaping(self, saw_type: SawType) -> SawType:
        """Mark a function type bound to a container's type parameter as
        escaping. Delegates to `mono_identity`."""
        return mark_stored_closure_escaping(saw_type)

    def _ensure_monomorphized_struct(self, struct_name: str, type_args: List[SawType]) -> str:
        """Ensure a monomorphized version of a generic struct exists.
        Returns the mangled name of the monomorphized struct."""
        # Fill omitted trailing type args from defaults before building the
        # type mapping, so `Vector<Int>` binds A=Global (not leaving A unbound)
        # and produces the same struct identity as `Vector<Int, Global>`.
        type_args = self._fill_default_type_args(struct_name, type_args)
        # Re-tag any STRUCT-kinded arg that is really an enum so the binding
        # stored in the monomorphization context carries kind ENUM, and enum
        # drop glue is selected for owning enum-payload elements. Kind is not
        # part of the mangling, so identity is unchanged.
        type_args = [self._canonicalize_type_kind(a) for a in type_args]
        # A function type bound to a container's type param is a stored
        # (escaping) closure: it lives in the buffer, so its env must be
        # retained on copy and released at teardown. The escaping bit is not
        # part of the mangling and is lost when a type arg is reconstructed
        # from a mangled name, so restore it here; otherwise the element reads
        # as non-owning and the env leaks or is not retained.
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

        # Publish before lowering, on the same terms as `_register_struct`
        # (design 246). The discipline lives here, in the registration helper,
        # rather than at the call sites, so it travels with the helper wherever
        # it is called from.
        llvm_struct_type = self.module.context.get_identified_type(mangled_name)
        field_order = [field.name for field in generic_struct.fields]
        self.struct_types[mangled_name] = (llvm_struct_type, field_order)

        # Generate field types with substitution
        field_types = []
        for field in generic_struct.fields:
            substituted = self._substitute_saw_type(field.type, type_mapping)
            field_types.append(self._get_llvm_type(substituted))
        self._set_registered_body(llvm_struct_type, field_types, mangled_name)
        # Record base name + concrete args so a monomorphized method can rebuild
        # its receiver's SawType (`_receiver_saw_type`), e.g. for a deinit's
        # appended field cleanup.
        self.mono_struct_args[mangled_name] = (struct_name, list(type_args))

        # Restore context.
        self.type_param_context = old_context

        # Layout only: the struct's method instances are the monomorphization
        # phase's to decide and splice in.
        return mangled_name

    def _ensure_monomorphized_enum(self, enum_name: str, type_args: List[SawType]) -> str:
        """Ensure a monomorphized version of a generic enum exists.
        Returns the mangled name of the monomorphized enum."""
        # Fill omitted trailing type args from defaults (identity rule).
        type_args = self._fill_default_type_args(enum_name, type_args)
        # Re-tag STRUCT-kinded args that are really enums (e.g. a
        # `MapSlot<K, V>` payload type) so nested enum drop glue is selected.
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

        # Create substituted variants.
        #
        # The raw backing rides along. Substitution rebuilds each variant, and
        # rebuilding it without `raw_value` would silently drop the declared
        # tag: `_register_concrete_enum` would fall back to ordinals, so
        # `Code<Int>.Warn as UInt8` would give 1 where the source says 20. A
        # declared backing is a wire format, so that corruption would have no
        # diagnostic (design 145). Only the payload types depend on the
        # instantiation; the tag values are the enum's own.
        substituted_variants = []
        for variant in generic_enum.variants:
            substituted_types = []
            for param_name, param_type in variant.associated_types:
                substituted = self._substitute_saw_type(param_type, type_mapping)
                substituted_types.append((param_name, substituted))
            substituted_variants.append(EnumVariant(
                name=variant.name,
                associated_types=substituted_types,
                raw_value=variant.raw_value,
                raw_line=variant.raw_line,
                raw_column=variant.raw_column,
            ))

        # Restore context before registering (registration will use _get_llvm_type)
        self.type_param_context = old_context

        # Register the monomorphized enum. The backing type is the enum's, not
        # the instantiation's (never a type parameter), so it passes through
        # unsubstituted; without it `_register_concrete_enum` takes its ordinal
        # path whatever the variants say.
        self._register_concrete_enum(mangled_name, substituted_variants,
                                     raw_type=generic_enum.raw_type)
        # The struct map's twin, and what `_receiver_saw_type` reads to rebuild
        # an ENUM-kinded receiver for the methods spliced onto this
        # instantiation.
        self.mono_enum_args[mangled_name] = (enum_name, list(type_args))

        return mangled_name

    def _receiver_saw_type(self, type_name: str) -> SawType:
        """The receiver's own `SawType` for an extension on `type_name`.

        A mangled name is a symbol, not a type. `Vector$2$Int$GlobalAllocator`
        answers no field lookup, resolves no variant and selects no drop glue;
        the base plus its concrete arguments do all three, and
        `mono_struct_args` / `mono_enum_args` are where that pair was recorded
        when the instantiation registered its layout. Every monomorphized
        method body is generated by the ordinary generators, which are handed
        the receiver's name and ask this for the type behind it.

        A name no instantiation registered is not monomorphized, and its answer
        is `_ext_self_types`'.
        """
        base_args = self.mono_struct_args.get(type_name)
        if base_args is not None:
            base, args = base_args
            return SawType(TypeKind.STRUCT, struct_name=base,
                           type_args=list(args))
        base_args = self.mono_enum_args.get(type_name)
        if base_args is not None:
            base, args = base_args
            return SawType(TypeKind.ENUM, enum_name=base,
                           type_args=list(args))
        return self._ext_self_types(type_name)[1]

    def _register_registry_type_instances(self):
        """Register the layout of every type instance the registry holds.

        This has to happen up front: the monomorphization phase splices each
        instantiation's methods in as an ordinary concrete extension whose
        `struct_name` is the mangled name, and `_declare_extension_methods`
        reads that name straight out of `struct_types` / `enum_types` to type
        the `self` parameter. Lazily registering the layout at the first use of
        the type cannot serve a declaration pass keyed on the symbol.

        Registration order is the registry's discovery order: first demands
        in a walk of the roots in declaration order, then of each demanded
        instance in FIFO worklist order. It is the order the module's
        identified types are created in, so it must stay deterministic
        (irdet).
        """
        registry = getattr(self, 'mono_registry', None)
        if registry is None:
            return
        for key in registry.order:
            inst = registry.instances[key]
            if instance_is_lowered_specially(inst.base, inst.args):
                # An instantiation `_get_llvm_type` intercepts has no layout of
                # its own to register — see the predicate for the two families.
                # The splice declines its methods on the same answer, so nothing
                # looks one up either.
                continue
            if inst.kind == 'struct':
                self._ensure_monomorphized_struct(inst.base, list(inst.args))
            elif inst.kind == 'enum':
                self._ensure_monomorphized_enum(inst.base, list(inst.args))

    # The overload tag `mangle_overload` appends. Split on it to move an overload
    # signature from one base to another.
    _OVERLOAD_TAG = "$OL$"

    @staticmethod
    def _compose_overload_suffix(mangled_name: str, method) -> str:
        """Carry a method's overload signature onto its monomorphized symbol.

        The typechecker stamps an overload's codegen symbol against the generic
        type's name (`Holder_take$OL$String`), because that is the only name a
        declaration has. The monomorphized symbol is the specialized base plus
        that stamped signature (`Holder$1$Int_take$OL$String`); without the
        signature, two overloads in a generic extension would share one
        symbol. A non-overloaded method has no tag and is untouched. Called by
        `calls.py`'s two method-call paths when the stamped symbol misses;
        `monomorphize.py` composes the same key itself (`_OVERLOAD_TAG`).
        """
        stamped = getattr(method, 'mangled_symbol', None)
        if not stamped or GenericsMixin._OVERLOAD_TAG not in stamped:
            return mangled_name
        suffix = stamped[stamped.index(GenericsMixin._OVERLOAD_TAG):]
        return mangled_name + suffix

    def _ensure_monomorphized_generic_method(self, mangled_struct_name: str,
                                             recv_type: SawType, method_name: str,
                                             method_type_args: List[SawType]) -> str:
        """The mangled symbol of a generic method's instantiation (design 36).

        A lookup, on `_instantiate_generic_function`'s terms: the
        monomorphization phase decides which (receiver args, method args) pairs
        exist, materializes each body and splices it in as an ordinary concrete
        method of a concrete extension, which the eager declaration pass has
        already declared. `recv_type` names the base in a miss report.

        A miss is an internal error: the standing decides-vs-lowers gate. It
        says the fixpoint failed to enumerate a demand this lowering makes.
        """
        mangled_name = self._mangle_method_name(mangled_struct_name, method_name,
                                                method_type_args=method_type_args)
        if mangled_name in self.functions:
            return mangled_name
        base_name = recv_type.struct_name or mangled_struct_name
        raise ValueError(
            f"internal compiler error: monomorphization did not discover the "
            f"instance `{mangled_name}` of generic method "
            f"`{base_name}.{method_name}`, demanded while lowering "
            f"{self._current_llvm_function_name() or '<registration>'}")


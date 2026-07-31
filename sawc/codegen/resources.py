"""
Resource management utilities for the Saw code generator.

This module provides mixin methods for handling resource cleanup, including:
- Determining cleanup behavior for types (Deinit, ImplicitCopy, NoCopy)
- Generating deinit calls for proper destruction
- Generating copy calls for ImplicitCopy types
- Managing scope-based cleanup for deterministic resource management

Usage:
    class CodeGenerator(ResourcesMixin, ...):
        pass
"""

from typing import Optional, List
from llvmlite import ir
from ast_nodes import (SawType, TypeKind, MoveExpr, Identifier, MemberAccess,
                       ArrayIndex, TupleIndex, SelfExpr,
                       FunctionCall, MethodCall, StructInit, EnumInit)
from .mangle import mangle_type


class ResourcesMixin:
    """Mixin providing resource management methods for CodeGenerator.

    Methods:
        _get_type_name_for_conformance: Get canonical name for interface lookup
        _get_cleanup_behavior: Determine how a type should be cleaned up
        _needs_cleanup: Check if a type requires cleanup
        _generate_deinit_call: Generate deinit() call for a variable
        _generate_copy: Generate copy() call for ImplicitCopy types
        _needs_copy_for_struct_init: Check if struct field init needs copy
        _cleanup_scope: Clean up variables in a scope
        _cleanup_all_scopes: Clean up all scopes (for early return)
    """

    def _get_type_name_for_conformance(self, saw_type: SawType) -> Optional[str]:
        """Get the registry key for an interface-conformance lookup.

        Interface conformances are registered under the *base* (unmangled) name
        of a type: `extension Box<T>: Deinit` registers 'Box', which then holds
        for every monomorphization `Box<Int>`, `Box<String>`, ... So a generic
        instantiation is looked up by its base name, NOT by a name that embeds
        the type arguments. (The method *symbol* for the monomorphized deinit/
        copy is a separate concern -- see `_type_method_base`, which routes
        through the canonical mangler so it matches the registered symbol.)
        """
        if saw_type.kind == TypeKind.STRING:
            # String is a compiler-known ImplicitCopy + Deinit type.
            return "String"
        if saw_type.kind == TypeKind.STRUCT:
            return saw_type.struct_name
        elif saw_type.kind == TypeKind.ENUM:
            return saw_type.enum_name
        return None

    def _primitive_self_llvm_type(self, struct_name: str):
        """The LLVM `self` type for a method in an extension on a primitive
        pseudo-struct (String/Int/Float, design 57), or None for an ordinary
        struct. String is i8*; Int is the platform word; Float is a double."""
        if struct_name == "String":
            return ir.IntType(8).as_pointer()
        if struct_name == "Int":
            return self.int_type
        if struct_name == "Float":
            return ir.DoubleType()
        return None

    def _type_method_base(self, saw_type: SawType) -> Optional[str]:
        """Base symbol for a type's compiler-invoked methods (deinit / copy).

        This must match the name the method was REGISTERED under. Monomorphized
        methods are registered as `mangle_method(mangle_named(base, args), m)`
        (e.g. `Box<Int>.deinit` -> `Box$1$Int_deinit`), so the base here is the
        canonical `mangle_type` of the (struct/enum) type. String's compiler-
        provided methods use the base 'String'. Non-generic types mangle to
        their plain name, so their symbols are unchanged.
        """
        if saw_type.kind == TypeKind.STRING:
            return "String"
        # Primitive pseudo-structs carrying method extensions (design 57).
        if saw_type.kind == TypeKind.INT:
            return "Int"
        if saw_type.kind == TypeKind.FLOAT:
            return "Float"
        if saw_type.kind in (TypeKind.STRUCT, TypeKind.ENUM):
            return mangle_type(saw_type)
        return None

    def _get_cleanup_behavior(self, saw_type: SawType) -> str:
        """Determine cleanup behavior for a type.

        Returns one of:
        - 'none': No special cleanup needed (plain types)
        - 'deinit': Type implements Deinit (or ExplicitCopy, which has a deinit
          and is never implicitly copied), call deinit() on drop
        - 'implicit_copy': Type implements ImplicitCopy, call copy() on copy
        - 'no_copy': Type implements NoCopy, cannot be copied

        Results are cached in self.type_cleanup_behavior.
        """
        type_name = self._get_type_name_for_conformance(saw_type)
        if type_name is None:
            return "none"

        # Check cache
        if type_name in self.type_cleanup_behavior:
            return self.type_cleanup_behavior[type_name]

        # Check conformances (use namespace)
        conformances = self.namespace.get_conformances(type_name)

        if "NoCopy" in conformances:
            behavior = "no_copy"
        elif "ImplicitCopy" in conformances:
            behavior = "implicit_copy"
        elif self.namespace.is_implicit_copy_enum(saw_type):
            # An enum can't declare ImplicitCopy; an owning-payload enum
            # (e.g. `DepSource { PathDep(String) }`) is structurally ImplicitCopy
            # and must copy-with-retain (DF12) — mirrors the typechecker. The
            # helper normalizes a STRUCT-kinded-but-actually-enum SawType and
            # returns False for genuine structs, so no `kind` guard is needed.
            behavior = "implicit_copy"
        elif "ExplicitCopy" in conformances:
            # ExplicitCopy has a deinit and is never implicitly copied (the
            # typechecker enforces `move`/`.copy()` at transfer sites), so for
            # codegen it behaves like a plain Deinit type: run deinit on drop.
            behavior = "deinit"
        elif "Deinit" in conformances:
            behavior = "deinit"
        else:
            behavior = "none"

        self.type_cleanup_behavior[type_name] = behavior
        return behavior

    def _needs_cleanup(self, saw_type: SawType) -> bool:
        """Check if a type needs cleanup.

        A type needs cleanup if it declares a resource trait (Deinit / NoCopy /
        ImplicitCopy / ExplicitCopy) OR -- even with no declared conformance --
        it transitively holds a value needing cleanup:
        - a struct with a cleanup-needing field (brief 17);
        - an enum whose any variant carries a cleanup-needing payload field
          (brief 23 item 1) -- enums dodge the containment rules entirely, so
          this "needs cleanup" test is what makes an undeclared enum holding a
          Deinit payload get its active variant released at scope exit;
        - an `Optional<T>` whose inner `T` needs cleanup (brief 23 item 1 probe).
        """
        # `Box<any Trait, A>` (design 51) always owns a heap payload: its erased
        # teardown (vtable destructor + dealloc) must run at scope death.
        if self._is_erased_box(saw_type):
            return True
        # A named type that actually denotes an ENUM can reach here still tagged
        # STRUCT (design 61, L14: the parser can't know; not every path is
        # canonicalized). Left as-is it would fall to the struct-field path below,
        # which finds no fields AND poisons the shared cache under the bare name
        # with `False` — so the enum's own `_enum_needs_variant_cleanup` then reads
        # that stale `False` and an owning enum payload (e.g. an `Arc` inside a
        # `Vector<enum>` slot) is treated as non-owning: leaked drop glue, and (for
        # design 65's copy-with-retain) no retain. Re-tag to ENUM first.
        if (saw_type.kind == TypeKind.STRUCT and saw_type.struct_name
                and (saw_type.struct_name in self.enum_types
                     or saw_type.struct_name in self.generic_enums)):
            saw_type = SawType(TypeKind.ENUM, enum_name=saw_type.struct_name,
                               type_args=saw_type.type_args, symbol=saw_type.symbol)
        if self._get_cleanup_behavior(saw_type) != "none":
            return True
        # An escaping closure value (design 71) is an OWNING value: it may carry a
        # heap environment whose destructor releases owned captures and frees the
        # block. Its drop glue null-checks the value's carried dtor pointer, so a
        # non-owning closure (no captures / borrow-only) is a safe no-op. A
        # non-escaping closure borrows the enclosing frame and owns nothing.
        if saw_type.kind == TypeKind.FUNCTION:
            return bool(getattr(saw_type, 'func_is_escaping', False))
        if saw_type.kind == TypeKind.ENUM:
            return self._enum_needs_variant_cleanup(saw_type)
        if saw_type.kind == TypeKind.OPTIONAL:
            return (saw_type.inner_type is not None
                    and self._needs_cleanup(saw_type.inner_type))
        if saw_type.kind == TypeKind.ARRAY:
            # A fixed array `[T; N]` needs cleanup iff its element type does
            # (design 33): each live element is destroyed at scope death.
            return (saw_type.array_element_type is not None
                    and self._needs_cleanup(saw_type.array_element_type))
        return self._struct_needs_field_cleanup(saw_type)

    def _concrete_field_types(self, saw_type: SawType):
        """Concrete field SawTypes for a struct value, substituting generic type
        arguments (so `Box<String>`'s `value` field resolves to `String`).

        Returns a {field_name: SawType} dict, or None if the struct's fields are
        not known (e.g. a monomorphization whose template fields aren't
        recorded)."""
        if saw_type.kind != TypeKind.STRUCT:
            return None
        name = saw_type.struct_name
        fields = self.namespace.get_struct_fields(name)
        if not fields:
            return None
        if saw_type.type_args and name in self.generic_structs:
            tmpl = self.generic_structs[name]
            mapping = {tp.name: ta
                       for tp, ta in zip(tmpl.type_params, saw_type.type_args)}
            return {fn: self._substitute_saw_type(ft, mapping)
                    for fn, ft in fields.items()}
        return dict(fields)

    def _struct_field_saw_type(self, struct_name: str, field_name: str):
        """Concrete SawType of `struct_name`'s field `field_name`, or None.

        `struct_name` may be a plain struct name or a monomorphized generic key
        (e.g. `Map$3$Int$Int$CountAlloc`); in the latter case the base name and
        type args are recovered from `mono_struct_args` so the field type
        substitutes its type params (a `Vector<..., A>` field resolves `A` to the
        instantiation's concrete allocator). Used by field-assignment release."""
        base_args = self.mono_struct_args.get(struct_name)
        if base_args is not None:
            base_name, targs = base_args
            saw = SawType(TypeKind.STRUCT, struct_name=base_name,
                          type_args=list(targs))
        else:
            saw = SawType(TypeKind.STRUCT, struct_name=struct_name)
        fields = self._concrete_field_types(saw)
        if not fields:
            return None
        return fields.get(field_name)

    def _struct_needs_field_cleanup(self, saw_type: SawType) -> bool:
        """Whether a struct transitively holds any field that needs cleanup.

        Cached by the canonical type symbol so `Box<Int>` (field Int, no cleanup)
        and `Box<String>` (field String, cleanup) are distinguished. Structs
        cannot contain themselves by value, so the graph is acyclic; the cache is
        seeded False before recursing as a belt-and-braces cycle guard.
        """
        if saw_type.kind != TypeKind.STRUCT:
            return False
        key = mangle_type(saw_type)
        cached = self.type_field_cleanup.get(key)
        if cached is not None:
            return cached
        self.type_field_cleanup[key] = False
        result = False
        field_types = self._concrete_field_types(saw_type)
        if field_types:
            for ftype in field_types.values():
                if self._needs_cleanup(ftype):
                    result = True
                    break
        self.type_field_cleanup[key] = result
        return result

    def _enum_key(self, saw_type: SawType) -> Optional[str]:
        """The `enum_types` registry key for an enum SawType, or None if the enum
        is not registered. Matches the mangling used at construction/match sites
        (`mangle_named(enum_name, type_args)`)."""
        if saw_type.kind != TypeKind.ENUM:
            return None
        key = mangle_type(saw_type)
        return key if key in self.enum_types else None

    def _enum_needs_variant_cleanup(self, saw_type: SawType) -> bool:
        """Whether any variant of an enum carries a payload field needing cleanup.

        Reads the registered (already-monomorphized, so concrete) variant field
        types. Cached by the canonical enum symbol, seeded False before recursing
        as a cycle guard (an enum could reach itself through an Optional payload).
        """
        key = self._enum_key(saw_type)
        if key is None:
            return False
        cached = self.type_field_cleanup.get(key)
        if cached is not None:
            return cached
        self.type_field_cleanup[key] = False
        result = False
        _, _, variant_info = self.enum_types[key]
        for fields in variant_info.values():
            if any(self._needs_cleanup(ftype) for _, ftype in fields):
                result = True
                break
        self.type_field_cleanup[key] = result
        return result

    def _is_owned_temporary(self, expr) -> bool:
        """Whether `expr` produces a fresh, owned value that no binding holds.

        Calls and constructors mint a new value the caller owns: if it is not
        bound, returned, or transferred onward, nobody will clean it, so it must
        be registered as a statement-scoped temporary (item 4). An lvalue path
        (Identifier / self / field / element access) instead *borrows* a value
        owned by an existing binding, which runs its own cleanup -- registering
        one of those as a temporary would double-free it.
        """
        return isinstance(expr, (FunctionCall, MethodCall, StructInit, EnumInit))

    def _register_stmt_temp(self, value, saw_type: SawType):
        """Spill an owned temporary `value` to a slot and register it for LIFO
        release at the end of the enclosing full statement. No-op outside a
        statement context or for values that need no cleanup."""
        if self.statement_temps is None or value is None:
            return None
        if not self._needs_cleanup(saw_type):
            return None
        slot = self._entry_alloca(value.type, name="stmt_temp")
        self.builder.store(value, slot)
        self.statement_temps.append((slot, saw_type))
        return slot

    def _generate_deinit_call(self, var_name: str, saw_type: SawType):
        """Generate cleanup (drop glue) for a variable at scope exit.

        The variable's storage is a pointer (alloca); dispatch to the recursive
        drop routine, which either calls a declared/compiler-known `deinit`
        method or, for a struct with no declared deinit, releases its
        cleanup-needing fields directly.
        """
        var_ptr = self.variables.get(var_name)
        if var_ptr is None:
            return
        self._emit_drop_at(var_ptr, saw_type)

    def _emit_drop_at(self, ptr, saw_type: SawType):
        """Emit cleanup for the value stored at `ptr` (a pointer to it).

        Compositional drop glue:
        1. If the type has a declared or compiler-provided `deinit` method, call
           it. That method is self-contained: for a user-declared struct deinit,
           the user body runs first and field cleanup is appended at the end
           (`_generate_field_deinit_calls`); `String`/`Vector` deinits are the
           compiler-provided release/free.
        2. Otherwise (a struct that needs cleanup only because it holds
           cleanup-needing fields), release those fields directly, in reverse
           declaration order.
        """
        # `Box<any Trait, A>` (design 51): teardown is driven by the vtable
        # (destructor + size + align), not a monomorphized `Box_deinit` — the
        # payload is erased, so there is no static `sizeof<T>`.
        if self._is_erased_box(saw_type):
            self._emit_erased_box_drop(ptr, saw_type)
            return
        method_base = self._type_method_base(saw_type)
        if method_base is not None:
            deinit_name = self._mangle_method_name(method_base, "deinit")
            fn = self.functions.get(deinit_name)
            if fn is not None:
                self.builder.call(fn, [ptr])
                return
        if saw_type.kind == TypeKind.FUNCTION:
            self._emit_closure_drop_at(ptr, saw_type)
            return
        if saw_type.kind == TypeKind.ENUM:
            self._emit_enum_cleanup_at(ptr, saw_type)
            return
        if saw_type.kind == TypeKind.OPTIONAL:
            self._emit_optional_cleanup_at(ptr, saw_type)
            return
        if saw_type.kind == TypeKind.ARRAY:
            self._emit_array_cleanup_at(ptr, saw_type)
            return
        self._emit_field_cleanup_at(ptr, saw_type)

    def _emit_closure_drop_at(self, ptr, saw_type: SawType):
        """Drop the closure value stored at `ptr` (design 71).

        A closure value is `{ fn_ptr, env_ptr, dtor_ptr }`. Dropping it runs its
        carried env destructor (which releases owned captures exactly once and
        frees the heap env block) when the dtor pointer is non-null; a non-owning
        closure (no captures / borrow-only / non-escaping) carries a null dtor and
        drops as a no-op. This is the single drop site for a closure wherever it
        flows — bound to a `let`/`var`, a struct field, a Vector element, or a
        returned value — so it composes with the LIFO/drop-flag machinery like any
        other owning value.
        """
        closure_val = self.builder.load(ptr, name="closure_drop")
        if (not isinstance(closure_val.type, ir.LiteralStructType)
                or len(closure_val.type.elements) != 3):
            return
        env_ptr = self.builder.extract_value(closure_val, 1, name="drop_env")
        dtor_ptr = self.builder.extract_value(closure_val, 2, name="drop_dtor")
        null_dtor = ir.Constant(dtor_ptr.type, None)
        has_dtor = self.builder.icmp_unsigned("!=", dtor_ptr, null_dtor,
                                              name="closure_has_dtor")
        run_bb = self.builder.function.append_basic_block(name="closure_dtor.run")
        cont_bb = self.builder.function.append_basic_block(name="closure_dtor.cont")
        self.builder.cbranch(has_dtor, run_bb, cont_bb)
        self.builder.position_at_start(run_bb)
        self.builder.call(dtor_ptr, [env_ptr])
        if not self.builder.block.is_terminated:
            self.builder.branch(cont_bb)
        self.builder.position_at_start(cont_bb)

    def _emit_array_cleanup_at(self, array_ptr, saw_type: SawType):
        """Release every element of the fixed array at `array_ptr`, in REVERSE
        index order (design 33). The array is laid out `[N x T]`; each element is
        dropped through `_emit_drop_at` so Deinit/String/nested-aggregate elements
        run their own cleanup. Composes with `__deinit_in_place` (arrays nested in
        structs/enums reach here via `_emit_field_cleanup_at` /
        `_emit_enum_cleanup_at`).
        """
        elem_type = saw_type.array_element_type
        size = saw_type.array_size
        if elem_type is None or size is None or not self._needs_cleanup(elem_type):
            return
        i32 = ir.IntType(32)
        for idx in reversed(range(size)):
            elem_ptr = self.builder.gep(
                array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, idx)],
                name=f"arr_drop_{idx}")
            self._emit_drop_at(elem_ptr, elem_type)

    def _emit_field_cleanup_at(self, struct_ptr, saw_type: SawType):
        """Release every cleanup-needing field of the struct at `struct_ptr`, in
        reverse field order (LIFO). Each field is dropped through `_emit_drop_at`
        so nested structs recurse and String/Deinit fields hit their release.

        This is the field half of drop glue: it never invokes the struct's OWN
        deinit (the caller already did, or there is none), only its fields.
        """
        if saw_type.kind != TypeKind.STRUCT:
            return
        struct_key = mangle_type(saw_type)
        info = self.struct_types.get(struct_key)
        if info is None:
            return
        _, field_order = info
        field_types = self._concrete_field_types(saw_type)
        if not field_types:
            return
        for field_name in reversed(field_order):
            ftype = field_types.get(field_name)
            if ftype is None or not self._needs_cleanup(ftype):
                continue
            idx = field_order.index(field_name)
            field_ptr = self.builder.gep(struct_ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), idx)
            ], name=f"{field_name}_ptr")
            self._emit_drop_at(field_ptr, ftype)

    def _emit_enum_cleanup_at(self, enum_ptr, saw_type: SawType):
        """Release the active variant's cleanup-needing payload fields of the enum
        at `enum_ptr`, by switching on the runtime tag (brief 23 item 1).

        The enum is laid out `{ i32 tag, [N x i8] payload }`. For each variant
        that carries any cleanup-needing field we emit a switch case that bitcasts
        the payload bytes to that variant's field struct and drops those fields in
        reverse declaration order (LIFO). Variants with nothing to release (and a
        simple tag-only enum) fall through the switch default and do nothing, so
        the inactive variants are never touched -- no double-free across variants.
        """
        key = self._enum_key(saw_type)
        if key is None:
            return
        llvm_enum_type, variant_tags, variant_info = self.enum_types[key]
        # Tag-only enum (no payload): nothing to release.
        if isinstance(llvm_enum_type, ir.IntType):
            return

        cleanup_variants = [
            name for name, fields in variant_info.items()
            if any(self._needs_cleanup(ftype) for _, ftype in fields)
        ]
        if not cleanup_variants:
            return

        i32 = ir.IntType(32)
        tag_ptr = self.builder.gep(
            enum_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], name="drop_tag_ptr")
        tag = self.builder.load(tag_ptr, name="drop_tag")

        func = self.builder.function
        cont_bb = func.append_basic_block("enum_drop_cont")
        switch = self.builder.switch(tag, cont_bb)

        variant_blocks = []
        for name in cleanup_variants:
            bb = func.append_basic_block(f"enum_drop_{name}")
            switch.add_case(ir.Constant(i32, variant_tags[name]), bb)
            variant_blocks.append((name, bb))

        for name, bb in variant_blocks:
            self.builder.position_at_end(bb)
            fields = variant_info[name]
            param_types = [self._get_llvm_type(ftype) for _, ftype in fields]
            param_struct_type = ir.LiteralStructType(param_types)
            payload_ptr = self.builder.gep(
                enum_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)],
                name="drop_payload_ptr")
            struct_ptr = self.builder.bitcast(
                payload_ptr, ir.PointerType(param_struct_type),
                name="drop_payload_struct")
            for idx in reversed(range(len(fields))):
                _, ftype = fields[idx]
                if not self._needs_cleanup(ftype):
                    continue
                field_ptr = self.builder.gep(
                    struct_ptr, [ir.Constant(i32, 0), ir.Constant(i32, idx)],
                    name="drop_payload_field")
                self._emit_drop_at(field_ptr, ftype)
            self.builder.branch(cont_bb)

        self.builder.position_at_end(cont_bb)

    def _emit_optional_cleanup_at(self, opt_ptr, saw_type: SawType):
        """Release the payload of an `Optional<T>` at `opt_ptr` when present (brief
        23 item 1 probe). Optionals are `{ i1 is_some, T }`: branch on the flag and
        drop the inner value only on the Some path. A None optional (flag 0, e.g. a
        moved-out or never-set slot) is skipped, so this never over-releases.
        """
        inner = saw_type.inner_type
        if inner is None or not self._needs_cleanup(inner):
            return
        i32 = ir.IntType(32)
        flag_ptr = self.builder.gep(
            opt_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], name="opt_drop_flag_ptr")
        is_some = self.builder.load(flag_ptr, name="opt_drop_is_some")

        func = self.builder.function
        some_bb = func.append_basic_block("opt_drop_some")
        cont_bb = func.append_basic_block("opt_drop_cont")
        self.builder.cbranch(is_some, some_bb, cont_bb)

        self.builder.position_at_end(some_bb)
        val_ptr = self.builder.gep(
            opt_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], name="opt_drop_val_ptr")
        self._emit_drop_at(val_ptr, inner)
        self.builder.branch(cont_bb)

        self.builder.position_at_end(cont_bb)

    # ===== Copy-with-retain glue (design 65, L17) =====
    #
    # The exact mirror of the drop glue above. `_emit_drop_at` RELEASES an owning
    # value's refcounts; `_emit_retain_at` BUMPS them, in place, so a bitwise
    # duplicate of an aggregate becomes a genuinely-owned independent copy whose
    # eventual drop is balanced. Used to copy-with-retain a struct/enum read out
    # of a container it stays in (e.g. a `Vector` slot via `.get()`): the whole
    # value is not a clean ImplicitCopy (it may be a NoCopy enum like `MapSlot`),
    # but its owning FIELDS (String/Arc/nested owners) must each be retained so
    # the map still owns its live payload after the peek.

    def _deep_copy_value(self, value, saw_type: SawType):
        """Return an independent, refcount-retained copy of `value` (design 65).

        Materializes the value in memory, bumps every owning field's refcount in
        place (mirroring drop glue), and reloads — the reloaded value shares the
        same buffers but with the refcounts bumped, so dropping it later releases
        exactly the retains taken here.
        """
        tmp = self._entry_alloca(value.type, name="retain_tmp")
        self.builder.store(value, tmp)
        self._emit_retain_at(tmp, saw_type)
        return self.builder.load(tmp, name="retained_copy")

    def _emit_retain_at(self, ptr, saw_type: SawType):
        """Bump the refcounts of the owning value stored at `ptr` (a pointer to
        it). The structural mirror of `_emit_drop_at`."""
        if not self._needs_cleanup(saw_type):
            return
        # A leaf with its own copy() (ImplicitCopy String/Arc/user type): retain
        # in place — copy() bumps the refcount and returns the (same-buffer)
        # value, which we store back.
        method_base = self._type_method_base(saw_type)
        if method_base is not None:
            copy_name = self._mangle_method_name(method_base, "copy")
            fn = self.functions.get(copy_name)
            if fn is not None:
                v = self.builder.load(ptr, name="retain_leaf")
                v2 = self.builder.call(fn, [v], name="retain_bump")
                self.builder.store(v2, ptr)
                return
        if saw_type.kind == TypeKind.ENUM:
            self._emit_enum_retain_at(ptr, saw_type)
            return
        if saw_type.kind == TypeKind.OPTIONAL:
            self._emit_optional_retain_at(ptr, saw_type)
            return
        if saw_type.kind == TypeKind.ARRAY:
            self._emit_array_retain_at(ptr, saw_type)
            return
        self._emit_field_retain_at(ptr, saw_type)

    def _emit_array_retain_at(self, array_ptr, saw_type: SawType):
        elem_type = saw_type.array_element_type
        size = saw_type.array_size
        if elem_type is None or size is None or not self._needs_cleanup(elem_type):
            return
        i32 = ir.IntType(32)
        for idx in range(size):
            elem_ptr = self.builder.gep(
                array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, idx)],
                name=f"arr_retain_{idx}")
            self._emit_retain_at(elem_ptr, elem_type)

    def _emit_field_retain_at(self, struct_ptr, saw_type: SawType):
        if saw_type.kind != TypeKind.STRUCT:
            return
        struct_key = mangle_type(saw_type)
        info = self.struct_types.get(struct_key)
        if info is None:
            return
        _, field_order = info
        field_types = self._concrete_field_types(saw_type)
        if not field_types:
            return
        for field_name in field_order:
            ftype = field_types.get(field_name)
            if ftype is None or not self._needs_cleanup(ftype):
                continue
            idx = field_order.index(field_name)
            field_ptr = self.builder.gep(struct_ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), idx)
            ], name=f"{field_name}_retain_ptr")
            self._emit_retain_at(field_ptr, ftype)

    def _emit_enum_retain_at(self, enum_ptr, saw_type: SawType):
        key = self._enum_key(saw_type)
        if key is None:
            return
        llvm_enum_type, variant_tags, variant_info = self.enum_types[key]
        if isinstance(llvm_enum_type, ir.IntType):
            return
        retain_variants = [
            name for name, fields in variant_info.items()
            if any(self._needs_cleanup(ftype) for _, ftype in fields)
        ]
        if not retain_variants:
            return
        i32 = ir.IntType(32)
        tag_ptr = self.builder.gep(
            enum_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], name="retain_tag_ptr")
        tag = self.builder.load(tag_ptr, name="retain_tag")
        func = self.builder.function
        cont_bb = func.append_basic_block("enum_retain_cont")
        switch = self.builder.switch(tag, cont_bb)
        variant_blocks = []
        for name in retain_variants:
            bb = func.append_basic_block(f"enum_retain_{name}")
            switch.add_case(ir.Constant(i32, variant_tags[name]), bb)
            variant_blocks.append((name, bb))
        for name, bb in variant_blocks:
            self.builder.position_at_end(bb)
            fields = variant_info[name]
            param_types = [self._get_llvm_type(ftype) for _, ftype in fields]
            param_struct_type = ir.LiteralStructType(param_types)
            payload_ptr = self.builder.gep(
                enum_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)],
                name="retain_payload_ptr")
            struct_ptr = self.builder.bitcast(
                payload_ptr, ir.PointerType(param_struct_type),
                name="retain_payload_struct")
            for idx in range(len(fields)):
                _, ftype = fields[idx]
                if not self._needs_cleanup(ftype):
                    continue
                field_ptr = self.builder.gep(
                    struct_ptr, [ir.Constant(i32, 0), ir.Constant(i32, idx)],
                    name="retain_payload_field")
                self._emit_retain_at(field_ptr, ftype)
            self.builder.branch(cont_bb)
        self.builder.position_at_end(cont_bb)

    def _emit_optional_retain_at(self, opt_ptr, saw_type: SawType):
        inner = saw_type.inner_type
        if inner is None or not self._needs_cleanup(inner):
            return
        i32 = ir.IntType(32)
        flag_ptr = self.builder.gep(
            opt_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], name="opt_retain_flag_ptr")
        is_some = self.builder.load(flag_ptr, name="opt_retain_is_some")
        func = self.builder.function
        some_bb = func.append_basic_block("opt_retain_some")
        cont_bb = func.append_basic_block("opt_retain_cont")
        self.builder.cbranch(is_some, some_bb, cont_bb)
        self.builder.position_at_end(some_bb)
        val_ptr = self.builder.gep(
            opt_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], name="opt_retain_val_ptr")
        self._emit_retain_at(val_ptr, inner)
        self.builder.branch(cont_bb)
        self.builder.position_at_end(cont_bb)

    # --- Release: the exact inverse of `_emit_retain_at` -----------------------
    #
    # Releases the value at `ptr` DOWN TO exactly what `_emit_retain_at` would
    # have retained — i.e. only refcounted (ImplicitCopy) leaves and the owning
    # fields reachable through them. Crucially it does NOT run the deinit of a
    # NoCopy-with-side-effect leaf (a `Deinit` struct that carries no refcount,
    # e.g. a `Val { id: Int }` counter): retain never bumped it (there is nothing
    # to bump), so release must not fire it. This is what lets an owning payload
    # field DISCARDED with `_` in a probe match (`Map._slot_state`,
    # `Map._key_eq`'s value) release a retained String/Arc without over-counting a
    # non-refcounted `Deinit` value — the design-61 exactly-once VALUE tests stay
    # green while owning KEYS/refcounted values are now balanced (design 65).

    def _emit_release_at(self, ptr, saw_type: SawType):
        if not self._needs_cleanup(saw_type):
            return
        # ImplicitCopy leaf (String/Arc/user copy()): retain bumped it, so release
        # is its ordinary drop (refcount decrement).
        method_base = self._type_method_base(saw_type)
        if method_base is not None:
            copy_name = self._mangle_method_name(method_base, "copy")
            if self.functions.get(copy_name) is not None:
                self._emit_drop_at(ptr, saw_type)
                return
        if saw_type.kind == TypeKind.ENUM:
            self._emit_enum_release_at(ptr, saw_type)
            return
        if saw_type.kind == TypeKind.OPTIONAL:
            self._emit_optional_release_at(ptr, saw_type)
            return
        if saw_type.kind == TypeKind.ARRAY:
            self._emit_array_release_at(ptr, saw_type)
            return
        self._emit_field_release_at(ptr, saw_type)

    def _emit_array_release_at(self, array_ptr, saw_type: SawType):
        elem_type = saw_type.array_element_type
        size = saw_type.array_size
        if elem_type is None or size is None or not self._needs_cleanup(elem_type):
            return
        i32 = ir.IntType(32)
        for idx in reversed(range(size)):
            elem_ptr = self.builder.gep(
                array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, idx)],
                name=f"arr_release_{idx}")
            self._emit_release_at(elem_ptr, elem_type)

    def _emit_field_release_at(self, struct_ptr, saw_type: SawType):
        if saw_type.kind != TypeKind.STRUCT:
            return
        struct_key = mangle_type(saw_type)
        info = self.struct_types.get(struct_key)
        if info is None:
            return
        _, field_order = info
        field_types = self._concrete_field_types(saw_type)
        if not field_types:
            return
        for field_name in reversed(field_order):
            ftype = field_types.get(field_name)
            if ftype is None or not self._needs_cleanup(ftype):
                continue
            idx = field_order.index(field_name)
            field_ptr = self.builder.gep(struct_ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), idx)
            ], name=f"{field_name}_release_ptr")
            self._emit_release_at(field_ptr, ftype)

    def _emit_enum_release_at(self, enum_ptr, saw_type: SawType):
        key = self._enum_key(saw_type)
        if key is None:
            return
        llvm_enum_type, variant_tags, variant_info = self.enum_types[key]
        if isinstance(llvm_enum_type, ir.IntType):
            return
        release_variants = [
            name for name, fields in variant_info.items()
            if any(self._needs_cleanup(ftype) for _, ftype in fields)
        ]
        if not release_variants:
            return
        i32 = ir.IntType(32)
        tag_ptr = self.builder.gep(
            enum_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], name="release_tag_ptr")
        tag = self.builder.load(tag_ptr, name="release_tag")
        func = self.builder.function
        cont_bb = func.append_basic_block("enum_release_cont")
        switch = self.builder.switch(tag, cont_bb)
        variant_blocks = []
        for name in release_variants:
            bb = func.append_basic_block(f"enum_release_{name}")
            switch.add_case(ir.Constant(i32, variant_tags[name]), bb)
            variant_blocks.append((name, bb))
        for name, bb in variant_blocks:
            self.builder.position_at_end(bb)
            fields = variant_info[name]
            param_types = [self._get_llvm_type(ftype) for _, ftype in fields]
            param_struct_type = ir.LiteralStructType(param_types)
            payload_ptr = self.builder.gep(
                enum_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)],
                name="release_payload_ptr")
            struct_ptr = self.builder.bitcast(
                payload_ptr, ir.PointerType(param_struct_type),
                name="release_payload_struct")
            for idx in reversed(range(len(fields))):
                _, ftype = fields[idx]
                if not self._needs_cleanup(ftype):
                    continue
                field_ptr = self.builder.gep(
                    struct_ptr, [ir.Constant(i32, 0), ir.Constant(i32, idx)],
                    name="release_payload_field")
                self._emit_release_at(field_ptr, ftype)
            self.builder.branch(cont_bb)
        self.builder.position_at_end(cont_bb)

    def _emit_optional_release_at(self, opt_ptr, saw_type: SawType):
        inner = saw_type.inner_type
        if inner is None or not self._needs_cleanup(inner):
            return
        i32 = ir.IntType(32)
        flag_ptr = self.builder.gep(
            opt_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], name="opt_release_flag_ptr")
        is_some = self.builder.load(flag_ptr, name="opt_release_is_some")
        func = self.builder.function
        some_bb = func.append_basic_block("opt_release_some")
        cont_bb = func.append_basic_block("opt_release_cont")
        self.builder.cbranch(is_some, some_bb, cont_bb)
        self.builder.position_at_end(some_bb)
        val_ptr = self.builder.gep(
            opt_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], name="opt_release_val_ptr")
        self._emit_release_at(val_ptr, inner)
        self.builder.branch(cont_bb)
        self.builder.position_at_end(cont_bb)

    def _generate_copy(self, value, saw_type: SawType):
        """Generate a copy of a value, calling copy() for ImplicitCopy types.

        Returns the copied value (which may be the original for non-ImplicitCopy types).

        For ImplicitCopy types, calls the copy(self) -> Self method.
        For regular types, returns the original value (bitwise copy).
        For NoCopy types, raises an error (should be caught by typechecker).
        """
        # A fixed array `[T; N]` copies per element (design 33). Only reached
        # implicitly for ImplicitCopy-element arrays (trivial arrays need no
        # copy; ExplicitCopy/NoCopy arrays are move-gated by the typechecker).
        # Resolve a generic type to the active monomorphization so the recursive
        # retain glue below can look up the concrete struct/enum layout.
        if self.type_param_context:
            saw_type = saw_type.substitute(self.type_param_context)

        if saw_type.kind == TypeKind.ARRAY:
            return self._emit_array_deep_copy(value, saw_type)

        # A type with its own copy() method (ImplicitCopy String/Arc/user) — call
        # it (a cheap refcount bump for String/Arc).
        type_name = self._type_method_base(saw_type)
        if type_name is not None:
            copy_method_name = self._mangle_method_name(type_name, "copy")
            copy_fn = self.functions.get(copy_method_name)
            if copy_fn is not None:
                # copy(self) takes self by value (immutable), returns Self.
                return self.builder.call(copy_fn, [value], name="copy_result")

        # No whole-type copy() method. If this is an aggregate that OWNS
        # cleanup-needing fields (a struct/enum/optional whose top-level copy class
        # is NoCopy only because of its owning payload — e.g. `MapSlot<String, V>`
        # or an `Arc` inside a struct payload), copy it WITH RETAIN recursively
        # (design 65, L17): reading such a value out of a container it stays in is
        # a duplication, so each owning field's refcount must be bumped and the
        # eventual drop of this copy releases them symmetrically. Trivial
        # aggregates (no owning fields) and genuine leaves fall through to bitwise.
        if (self._needs_cleanup(saw_type)
                and saw_type.kind in (TypeKind.STRUCT, TypeKind.ENUM,
                                      TypeKind.OPTIONAL)):
            return self._deep_copy_value(value, saw_type)

        # Regular / trivially-copyable types: bitwise copy (the value as-is).
        return value

    def _emit_copy_value(self, value, saw_type: SawType):
        """Produce an independent copy of a single value of `saw_type`.

        The per-element building block for array `.copy()` / implicit array copy
        (design 33). Dispatches: nested array -> per-element copy; trivially
        copyable -> the value as-is (bitwise); a type with a real `copy()` method
        (ImplicitCopy/ExplicitCopy, incl. String) -> a call to it. A resource
        type with no copy path never reaches here (the typechecker gates it).
        """
        if saw_type.kind == TypeKind.ARRAY:
            return self._emit_array_deep_copy(value, saw_type)
        if self.namespace.is_trivially_copyable(saw_type):
            return value
        method_base = self._type_method_base(saw_type)
        if method_base is not None:
            copy_name = self._mangle_method_name(method_base, "copy")
            fn = self.functions.get(copy_name)
            if fn is not None:
                return self.builder.call(fn, [value], name="elem_copy")
        # No copy path found: bitwise fallback (typechecker should have rejected).
        return value

    def _emit_array_deep_copy(self, value, saw_type: SawType):
        """Copy a fixed array `[T; N]` value element-by-element, in index order
        (design 33). Each element is duplicated through `_emit_copy_value`, so an
        ExplicitCopy/ImplicitCopy element runs its own `copy()` and the result is
        an independent array (mutating one leaves the other untouched; each owned
        element is released exactly once at its array's scope death)."""
        elem_type = saw_type.array_element_type
        size = saw_type.array_size
        if elem_type is None or size is None:
            return value
        result = value
        for idx in range(size):
            elem = self.builder.extract_value(value, idx, name=f"arr_cp_src{idx}")
            elem_copy = self._emit_copy_value(elem, elem_type)
            result = self.builder.insert_value(result, elem_copy, idx,
                                               name=f"arr_cp{idx}")
        return result

    def _gen_transfer_value(self, value_expr):
        """Generate a value being transferred into a new home (call argument,
        return value, aggregate element), honoring the typechecker's
        `needs_copy` annotation.

        The value-transfer checkpoint marks `expr.needs_copy = True` on any
        ImplicitCopy value read out of an existing binding, so codegen invokes
        `copy()` uniformly at every transfer site instead of re-deciding per
        site.

        Two transfer sites the typechecker checkpoint does NOT mark are also
        handled here, because they alias an owned ImplicitCopy value that then
        escapes into a new home:
        - `self` (a `&self` borrow returned/passed on) — SelfExpr is not in the
          checkpoint's aliasing set;
        - an inner-block tail expression (an if / if-let / match branch result
          that is a plain binding) — only function/method-body tails are
          checkpointed. Without the retain, the block's scope cleanup releases
          the local and frees the value before its consumer reads it.
        For ImplicitCopy `copy()` == retain, so re-deriving the decision here
        (instead of relying solely on `needs_copy`) yields the same result at
        already-checkpointed sites and closes these two gaps. It never
        double-copies: `_generate_copy` is invoked at most once per transfer.
        """
        # design 51: erase `&concrete` to `&any Trait` at the call boundary. The
        # typechecker tagged this argument; the underlying expression lowers to a
        # pointer to the concrete value, which we wrap into a fat pointer with the
        # (concrete, trait) vtable attached. A borrow — no move/copy.
        erase_trait = getattr(value_expr, 'erase_to_trait', None)
        if erase_trait is not None:
            data_ptr = self._generate_expression(value_expr)
            return self._erase_pointer_to_any(
                data_ptr, value_expr.erase_concrete, erase_trait)

        value = self._generate_expression(value_expr)
        if self._transfer_needs_copy(value_expr):
            value = self._generate_copy(value, self._expr_type(value_expr))
            # DF3 (design 57): a copied/retained value wrapped into an optional
            # parameter — the Some(...) owns the fresh reference.
            return self._maybe_autowrap_optional(value_expr, value)
        elif isinstance(value_expr, Identifier):
            # No copy/retain was needed, yet the value is being transferred into a
            # NEW home — for a named owned (ExplicitCopy/NoCopy) binding that means
            # its ownership is MOVING out (e.g. a tail-return `result` or
            # `return v` written without an explicit `move`, which the language
            # permits). The source must therefore NOT be dropped at scope exit:
            # clear its drop flag (design 42) and mark it moved for the unflagged
            # fallback path. An ImplicitCopy source took the `needs_copy` branch
            # above (retain — the source stays live), so it never reaches here.
            name = value_expr.name
            flag = self.drop_flags.get(name)
            if flag is not None:
                self.builder.store(ir.Constant(ir.IntType(1), 0), flag)
            self.moved_variables.add(name)
        return self._maybe_autowrap_optional(value_expr, value)

    def _maybe_autowrap_optional(self, value_expr, value):
        """DF3 (design 57): if the typechecker recorded a one-level `T -> T?`
        call-site auto-wrap on `value_expr`, construct the `{ i1 is_some, T }`
        optional around the already-materialized (and move/copy-resolved)
        `value`. Otherwise return `value` unchanged."""
        opt_type = getattr(value_expr, 'autowrap_to_optional', None)
        if opt_type is None:
            return value
        opt_llvm = self._get_llvm_type(opt_type)
        opt_val = ir.Constant(opt_llvm, ir.Undefined)
        opt_val = self.builder.insert_value(
            opt_val, ir.Constant(ir.IntType(1), 1), 0, name="autowrap_some")
        opt_val = self.builder.insert_value(opt_val, value, 1, name="autowrap_val")
        return opt_val

    def _transfer_needs_copy(self, value_expr) -> bool:
        """Whether transferring `value_expr` into a new owner must copy/retain."""
        if getattr(value_expr, 'needs_copy', False):
            return True
        # `self` and inner-block tails aren't marked by the checkpoint; retain
        # when they alias an ImplicitCopy value (copy() == cheap retain).
        if isinstance(value_expr, (Identifier, MemberAccess, ArrayIndex,
                                   TupleIndex, SelfExpr)):
            if getattr(value_expr, 'resolved_type', None) is None:
                return False
            t = self._expr_type(value_expr)
            # Resolve a generic element/field type (e.g. `Vector<T>.get`'s `T`) to
            # the active monomorphization's concrete type, so the kind/owning-field
            # checks below see the real `MapSlot<String,V>` / enum, not `T`.
            if self.type_param_context:
                t = t.substitute(self.type_param_context)
            if self._get_cleanup_behavior(t) == "implicit_copy":
                return True
            # design 65 (L17), extended (DF12): reading an owning aggregate (a
            # struct/enum/optional with cleanup-needing fields) OUT OF A CONTAINER
            # SLOT it stays in — an indexed element (`v[i]`), a struct FIELD
            # (`obj.field`), or a tuple element (`t.0`) — duplicates it while the
            # source keeps ownership. Moving out of such a projection is forbidden
            # (L1), so the read is always a duplication: its owning fields must be
            # retained (copy-with-retain in `_generate_copy`) so the copy's later
            # drop is balanced. Without this, passing e.g. a `Path`/`DepSource`
            # FIELD by value bitwise-aliased its `String`, which was then released
            # by the receiver's drop while the container still owned it -> double
            # free (DF12). A whole-binding read (a bare `Identifier`) is NOT here:
            # it may be a move, and an ImplicitCopy one is already caught above.
            if (isinstance(value_expr, (ArrayIndex, MemberAccess, TupleIndex))
                    and self._needs_cleanup(t)
                    and t.kind in (TypeKind.STRUCT, TypeKind.ENUM,
                                   TypeKind.OPTIONAL)):
                return True
            return False
        return False

    def _needs_copy_for_struct_init(self, value_expr, field_type: SawType) -> bool:
        """Check if a value expression needs copy() called during struct initialization.

        We need to call copy() when:
        1. The field type implements ImplicitCopy
        2. The value comes from an existing variable (Identifier) or field access (MemberAccess)

        We don't need copy() for:
        - Fresh struct/enum construction (new values don't need copying)
        - Literals (they don't have existing ownership)
        - Move expressions (ownership is transferred)
        """
        # Check if the field type implements ImplicitCopy
        behavior = self._get_cleanup_behavior(field_type)
        if behavior != "implicit_copy":
            return False

        # Check if the value comes from an existing binding that needs copying

        if isinstance(value_expr, MoveExpr):
            # Move expressions transfer ownership, no copy needed
            return False

        if isinstance(value_expr, Identifier):
            # Identifier refers to an existing variable - needs copy
            return True

        if isinstance(value_expr, MemberAccess):
            # Member access (e.g., self.field) - needs copy
            return True

        # Fresh construction (struct init, enum init, literals) doesn't need copy
        return False

    def _register_cleanup(self, var_name: str, saw_type: SawType):
        """Register a MOVABLE binding (let, param, if-let/guard binding) for
        scope-exit cleanup, with a runtime drop flag (design 42).

        The flag (i1, initialized 1 = needs-drop) is set to 0 by `move` so that a
        binding moved on only some paths is dropped exactly on the paths where it
        was not — the conditional-move correctness the flat `moved_variables` set
        cannot express. The flag is initialized at the CURRENT (declaration) point
        so a binding re-declared each loop iteration resets to needs-drop.
        """
        if not self.cleanup_stack:
            return
        self.cleanup_stack[-1].append((var_name, saw_type))
        flag = self._entry_alloca(ir.IntType(1), name=f"{var_name}.dropflag")
        self.builder.store(ir.Constant(ir.IntType(1), 1), flag)
        self.drop_flags[var_name] = flag

    def _cleanup_scope(self, scope_vars: List[tuple[str, SawType]]):
        """Generate cleanup code for all variables in a scope.

        Variables are cleaned up in reverse declaration order to ensure
        proper destruction semantics (LIFO). A binding with a runtime drop flag
        (registered via `_register_cleanup`) is dropped only if its flag is still
        set — correct under conditional moves. A binding without a flag (e.g. a
        statement-scoped temporary, never a `move` target) uses the static
        `moved_variables` skip.
        """
        for var_name, saw_type in reversed(scope_vars):
            if var_name not in self.variables:
                continue
            flag = self.drop_flags.get(var_name)
            if flag is not None:
                # Guard the drop on the runtime flag: `if flag { deinit }`.
                needs = self.builder.load(flag, name=f"{var_name}.needsdrop")
                drop_bb = self.builder.function.append_basic_block(
                    name=f"drop.{var_name}")
                cont_bb = self.builder.function.append_basic_block(
                    name=f"drop.{var_name}.cont")
                self.builder.cbranch(needs, drop_bb, cont_bb)
                self.builder.position_at_start(drop_bb)
                self._generate_deinit_call(var_name, saw_type)
                if not self.builder.block.is_terminated:
                    self.builder.branch(cont_bb)
                self.builder.position_at_start(cont_bb)
                continue
            # No drop flag: fall back to the static moved-variable skip.
            if var_name in self.moved_variables:
                continue
            self._generate_deinit_call(var_name, saw_type)

    def _cleanup_all_scopes(self):
        """Generate cleanup code for all scopes (for early return).

        Called before return statements to ensure all in-scope variables
        are properly cleaned up.
        """
        for scope_vars in reversed(self.cleanup_stack):
            self._cleanup_scope(scope_vars)

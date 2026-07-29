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
        if self._get_cleanup_behavior(saw_type) != "none":
            return True
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
        if saw_type.kind == TypeKind.ARRAY:
            return self._emit_array_deep_copy(value, saw_type)

        behavior = self._get_cleanup_behavior(saw_type)

        if behavior == "no_copy":
            # NoCopy types cannot be copied - this should be caught by typechecker
            raise ValueError(f"Cannot copy NoCopy type: {saw_type}")

        if behavior != "implicit_copy":
            # Regular types just use the value as-is (bitwise copy)
            return value

        # ImplicitCopy: call the copy() method
        type_name = self._type_method_base(saw_type)
        if type_name is None:
            return value

        copy_method_name = self._mangle_method_name(type_name, "copy")

        if copy_method_name not in self.functions:
            # No copy method found - fall back to bitwise copy
            return value

        copy_fn = self.functions[copy_method_name]

        # copy(self) takes self by value (immutable), returns Self
        return self.builder.call(copy_fn, [value], name="copy_result")

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
        return value

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
            return self._get_cleanup_behavior(self._expr_type(value_expr)) == "implicit_copy"
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

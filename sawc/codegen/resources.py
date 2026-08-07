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
                       FunctionCall, MethodCall, StructInit, EnumInit,
                       TupleLiteral, ArrayLiteral, MapLiteral, SetLiteral)
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
        of a type: `extension Box<T>: NoCopy` registers 'Box', which then holds
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

    def _enum_tag_llvm_type(self, enum_name: str):
        """The LLVM integer type of an enum's TAG.

        `i32` for every ordinary enum, so existing IR is byte-identical. A
        RAW-BACKED enum (design 145 unit B2) is exactly its declared backing
        width, because the backing pins the representation: `enum E: UInt8` is
        one byte, which is what makes it legal as a field of an
        `UnsafeMemory`-viewed wire struct."""
        entry = self.enum_types.get(enum_name)
        if entry is None:
            return ir.IntType(32)
        llvm_type = entry[0]
        if isinstance(llvm_type, ir.IntType):
            return llvm_type
        # Payload shape `{ tag, [N x i8] }`.
        return llvm_type.elements[0]

    def _ext_self_types(self, type_name: str):
        """The `(llvm_type, saw_type)` pair for `self` in `extension <type_name>`.

        One place that knows all three receiver shapes: a primitive
        pseudo-struct (design 57), an ENUM (design 145 — its LLVM type is a bare
        `i32` tag when payload-free, or `{i32, [N x i8]}` with payloads), and an
        ordinary struct. Getting the SawType KIND right matters as much as the
        LLVM type: a STRUCT-kinded `self` on an enum has no variants, so every
        `match self` in the body would fail to resolve its cases."""
        prim = self._primitive_self_llvm_type(type_name)
        if prim is not None:
            kind = {"String": TypeKind.STRING, "Int": TypeKind.INT,
                    "Float": TypeKind.FLOAT}[type_name]
            return prim, SawType(kind)
        if type_name in self.enum_types:
            return (self.enum_types[type_name][0],
                    SawType(TypeKind.ENUM, enum_name=type_name))
        return (self.struct_types[type_name][0],
                SawType(TypeKind.STRUCT, struct_name=type_name))

    def _type_method_base(self, saw_type: SawType) -> Optional[str]:
        """Base symbol for a type's compiler-invoked methods (deinit / copy).

        This must match the name the method was REGISTERED under. Monomorphized
        methods are registered as `mangle_method(mangle_named(base, args), m)`
        (e.g. `Box<Int>.deinit` -> `Box$1$Int_deinit`), so the base here is the
        canonical `mangle_type` of the (struct/enum) type. String's compiler-
        provided methods use the base 'String'. Non-generic types mangle to
        their plain name, so their symbols are unchanged.

        DEFAULT TYPE ARGUMENTS ARE FILLED FIRST (design 37, DF-128c). A field
        written `Vector<Int>` DENOTES `Vector<Int, GlobalAllocator>`, and that
        full form is what the monomorphized methods are registered under —
        `Vector$2$Int$GlobalAllocator_deinit`. Mangling the written form gave
        `Vector$1$Int`, and every consumer reads the resulting miss as "this
        type has no deinit of its own" and falls back to structural glue. So a
        struct holding a `Vector` field never ran the vector's own deinit: its
        elements leaked and its buffer was never freed. generics.py documents
        this chokepoint — every mangling of a named type funnels through
        `_fill_default_type_args` — and this caller was the one that skipped it.

        It could not be fixed alone. The missing drop CANCELLED `Vector.get`
        handing out a non-retained alias of a move-only element (DF-132a): the
        alias ran the element's deinit, the container's field glue did not, and
        each element was freed exactly once by accident. Fixing either half by
        itself frees twice. `get` is a place now, so this lands with it.
        """
        if saw_type.kind == TypeKind.STRING:
            return "String"
        # Primitive pseudo-structs carrying method extensions (design 57).
        if saw_type.kind == TypeKind.INT:
            return "Int"
        if saw_type.kind == TypeKind.FLOAT:
            return "Float"
        if saw_type.kind in (TypeKind.STRUCT, TypeKind.ENUM):
            name = (saw_type.struct_name if saw_type.kind == TypeKind.STRUCT
                    else saw_type.enum_name)
            args = list(saw_type.type_args or [])
            if name is not None:
                filled = self._fill_default_type_args(name, args)
                if len(filled) != len(args):
                    from codegen.mangle import mangle_named
                    return mangle_named(name, filled)
            return mangle_type(saw_type)
        return None

    def _is_borrowed_name(self, name: str) -> bool:
        """Is `name` bound to storage this frame BORROWS rather than owns?

        Two spellings answer differently and both must be caught: an ordinary
        reference parameter keeps its `&T` in `variable_types`, while a
        reference CLOSURE parameter stores the referent's type there (the name
        is the pointer itself) and is recorded in `borrowed_variables` instead.
        """
        if name in self.borrowed_variables:
            return True
        t = self.variable_types.get(name)
        return t is not None and t.kind == TypeKind.REFERENCE

    def _get_cleanup_behavior(self, saw_type: SawType) -> str:
        """Determine cleanup behavior for a type.

        Returns one of:
        - 'none': No special cleanup needed (plain types)
        - 'deinit': Type implements Deinit (or ExplicitCopy, which has a deinit
          and is never implicitly copied), call deinit() on drop
        - 'implicit_copy': Type implements ImplicitCopy, call copy() on copy
        - 'no_copy': Type implements NoCopy, cannot be copied

        Results are cached in self.type_cleanup_behavior. The cache key carries
        the TYPE ARGUMENTS, because one of the answers below is structural: a
        generic enum's tier comes from its instantiated payloads, so `Slot<K>`
        and `Slot<Res>` are two different answers under one base name. Keying on
        the base name alone let whichever was seen first decide for both — the
        abstract form always answers "none", so a concrete `Slot<Res>` read
        emitted no copy and DF-146e's over-release followed.
        """
        type_name = self._get_type_name_for_conformance(saw_type)
        if type_name is None:
            return "none"
        cache_key = (type_name,
                     tuple(str(a) for a in (saw_type.type_args or [])))

        # Check cache
        if cache_key in self.type_cleanup_behavior:
            return self.type_cleanup_behavior[cache_key]

        # Check conformances (use namespace)
        conformances = self.namespace.get_conformances(type_name)

        if "NoCopy" in conformances:
            behavior = "no_copy"
        elif "ImplicitCopy" in conformances:
            behavior = "implicit_copy"
        elif self.namespace.is_structurally_implicit_copy(saw_type):
            # The UNDECLARED ImplicitCopy tier, structs and enums alike
            # (design 159). An enum cannot declare ImplicitCopy at all, so an
            # owning-payload enum (`DepSource { PathDep(String) }`) has always
            # been classified here (DF12). A STRUCT whose owning members are
            # all trivial/ImplicitCopy — `struct P { name: String }`, a struct
            # holding a closure — is on exactly the same footing: the
            # containment checks deliberately exempt it from declaring a
            # policy, so the tier is automatic and this is the only place that
            # can report it.
            #
            # Answering "none" for that struct (DF-151b) is what made a copy
            # emit no retain while its per-binding drop still released every
            # field. `copy_tier` is the one oracle both kinds now ask, so
            # there is a single answer to "copy this composite" regardless of
            # how the tier arose.
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

        self.type_cleanup_behavior[cache_key] = behavior
        return behavior

    def _retag_enum(self, saw_type: SawType) -> SawType:
        """Re-tag a STRUCT-kinded type that actually names an ENUM.

        A named type reaches codegen still tagged STRUCT whenever nothing
        re-resolved it (design 61, L14: the parser cannot know which it is, and
        not every path canonicalizes). A STRUCT FIELD is the case that matters:
        `namespace.get_struct_fields` hands back the raw parsed annotation, so
        `struct Holder { slot: Slot }` describes its enum field as a struct.

        Every value-lifecycle dispatch below is keyed on `kind`, so a
        mis-tagged type falls off the end of the chain and emits NOTHING — no
        drop, no retain, no release. That is why an enum-typed struct field
        leaked its payload: the field was correctly judged cleanup-needing and
        then dropped by a path that had no idea it was looking at an enum.
        """
        if (saw_type is not None and saw_type.kind == TypeKind.STRUCT
                and saw_type.struct_name
                and (saw_type.struct_name in self.enum_types
                     or saw_type.struct_name in self.generic_enums)):
            return SawType(TypeKind.ENUM, enum_name=saw_type.struct_name,
                           type_args=saw_type.type_args, symbol=saw_type.symbol)
        return saw_type

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
        # Left tagged STRUCT this would fall to the struct-field path below,
        # which finds no fields AND poisons the shared cache under the bare name
        # with `False` — so the enum's own `_enum_needs_variant_cleanup` then reads
        # that stale `False` and an owning enum payload (e.g. an `Arc` inside a
        # `Vector<enum>` slot) is treated as non-owning: leaked drop glue, and (for
        # design 65's copy-with-retain) no retain. Re-tag to ENUM first.
        saw_type = self._retag_enum(saw_type)
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
        if saw_type.kind == TypeKind.TUPLE:
            # A tuple owns its elements exactly as a struct owns its fields
            # (design 139: a composite takes its strongest element's tier), so
            # it needs cleanup iff any element does. Named tuples included —
            # the names are a projection convenience, not a different type.
            # This arm was MISSING (DF-151f), and its absence was silent in
            # both directions: `_needs_cleanup` answered False, so no binding
            # ever registered a tuple for cleanup, and `_emit_drop_at` fell
            # through to the struct-field path, which finds no fields. A
            # `(Arc<Res>, Int)` local leaked its Arc with no error and no
            # crash.
            return any(self._needs_cleanup(e)
                       for e in (saw_type.element_types or [])
                       if e is not None)
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

        An aggregate LITERAL mints a value the same way (DF-151d): every one of
        them builds its elements through `_gen_transfer_value`, so a `(f(), k)`
        tuple, an `[s0, s1]` array and a `{k: v}` map each hold references they
        took themselves -- retained from a binding or moved off one. That makes
        the literal an owner, not a borrow, and an unclaimed one leaks exactly
        as an unclaimed call result does.
        """
        return isinstance(expr, (FunctionCall, MethodCall, StructInit, EnumInit,
                                 TupleLiteral, ArrayLiteral, MapLiteral,
                                 SetLiteral))

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
        """Generate cleanup (drop glue) for a variable being OVERWRITTEN.

        The variable's storage is a pointer (alloca); dispatch to the recursive
        drop routine, which either calls a declared/compiler-known `deinit`
        method or, for a struct with no declared deinit, releases its
        cleanup-needing fields directly.

        The drop is guarded exactly as scope exit guards its own (design 42): a
        binding that was MOVED OUT no longer owns anything, and `var x = ...;
        sink.push(move x); x = fresh` is the language's own revival idiom — the
        `move` transferred the value to the vector, so dropping it again at the
        reassignment frees what the vector holds. That double free was invisible
        while a `Vector` FIELD had no drop glue (DF-128c): the spurious drop
        reached a struct whose fields were never released, so it did nothing.
        Restoring the glue made it real, and it is what crashed blade's manifest
        reader — `TomlDoc.parse` moves its `current_section` into the document
        and starts a fresh one on every `[header]` line.
        """
        var_ptr = self.variables.get(var_name)
        if var_ptr is None:
            return
        self._emit_scope_var_drop(var_name, saw_type, var_ptr,
                                  self.drop_flags.get(var_name))

    def _revive_assigned_binding(self, var_name: str, saw_type: SawType):
        """A moved `var` REVIVES on reassignment — so it owns again.

        `move x` clears the binding's drop flag and marks it moved, which is
        what stops the scope from dropping a value it handed away. Assigning a
        fresh value makes it an owner once more, so the flag has to come back on
        or the new value leaks: nothing would ever release `x = fresh` after a
        `sink.push(move x)`. The static mark is cleared for the same reason.
        """
        if saw_type is None or not self._needs_cleanup(saw_type):
            return
        flag = self.drop_flags.get(var_name)
        if flag is not None:
            self.builder.store(ir.Constant(ir.IntType(1), 1), flag)
        self.moved_variables.discard(var_name)

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
        saw_type = self._retag_enum(saw_type)
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
        if saw_type.kind == TypeKind.TUPLE:
            self._emit_tuple_cleanup_at(ptr, saw_type)
            return
        self._emit_field_cleanup_at(ptr, saw_type)

    def _emit_closure_drop_at(self, ptr, saw_type: SawType):
        """Drop the closure value stored at `ptr` (design 71/73).

        A closure value is `{ fn_ptr, env_ptr, dtor_ptr }`. An escaping closure is
        ImplicitCopy over a refcounted heap env: dropping RELEASES one reference —
        it atomically decrements the env's leading refcount word and, only when
        this was the LAST owner (old count == 1), runs the carried env destructor
        (which releases owned captures and frees the heap block). A non-owning
        closure (no captures / borrow-only / non-escaping) carries a null dtor and
        drops as a no-op. This is the single drop/release site for a closure
        wherever it flows — bound to a `let`/`var`, a struct field, a Vector
        element, or a returned value — so it composes with the LIFO/drop-flag
        machinery like any other owning value.
        """
        closure_val = self.builder.load(ptr, name="closure_drop")
        if (not isinstance(closure_val.type, ir.LiteralStructType)
                or len(closure_val.type.elements) != 3):
            return
        env_ptr = self.builder.extract_value(closure_val, 1, name="drop_env")
        dtor_ptr = self.builder.extract_value(closure_val, 2, name="drop_dtor")
        self._emit_closure_env_release(env_ptr, dtor_ptr)

    def _emit_closure_env_release(self, env_ptr, dtor_ptr):
        """Release one reference to an escaping closure's refcounted heap env
        (design 73): atomic decrement of the leading refcount word, and at zero an
        acquire fence + the env destructor (captures release + block free). A null
        dtor (non-owning / capture-less / non-escaping closure) is a no-op.
        Shared by closure drop glue and the spawn trampoline."""
        word = self.int_type
        null_dtor = ir.Constant(dtor_ptr.type, None)
        has_dtor = self.builder.icmp_unsigned("!=", dtor_ptr, null_dtor,
                                              name="closure_has_dtor")
        with self.builder.if_then(has_dtor):
            rc_ptr = self.builder.bitcast(env_ptr, word.as_pointer(),
                                          name="env_rc_ptr")
            # Mirror String's atomic release: decrement with release ordering; the
            # last owner (old==1) acquires before running teardown + free.
            old = self.builder.atomic_rmw('sub', rc_ptr, ir.Constant(word, 1),
                                          ordering='release')
            is_last = self.builder.icmp_signed("==", old, ir.Constant(word, 1),
                                               name="env_last_owner")
            with self.builder.if_then(is_last):
                self.builder.fence(ordering='acquire')
                self.builder.call(dtor_ptr, [env_ptr])

    def _emit_array_cleanup_at(self, array_ptr, saw_type: SawType):
        """Release every element of the fixed array at `array_ptr`, in REVERSE
        index order (design 33). The array is laid out `[N x T]`; each element is
        dropped through `_emit_drop_at` so Deinit/String/nested-aggregate elements
        run their own cleanup. Composes with `__saw_deinit_in_place` (arrays nested in
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

    def _tuple_elements(self, saw_type: SawType):
        """The element SawTypes of a tuple, with the active monomorphization's
        type arguments substituted in. One place that knows how to read a
        tuple's parts, so the drop / retain / release / copy walkers below stay
        the same three lines each.

        Substitution matters for the same reason it does for a struct field: a
        `(T, Int)` local inside a generic body describes its first element with
        an opaque parameter, and every lifecycle decision below is made off the
        element's KIND. Left unsubstituted, `T = Arc<Res>` reads as an unknown
        struct that needs no cleanup.
        """
        elements = saw_type.element_types or []
        if self.type_param_context:
            elements = [e.substitute(self.type_param_context) if e is not None
                        else None for e in elements]
        return elements

    def _emit_tuple_cleanup_at(self, tuple_ptr, saw_type: SawType):
        """Release every cleanup-needing element of the tuple at `tuple_ptr`, in
        REVERSE position order (LIFO) — the same rule a struct's fields follow,
        for the same reason: a tuple is a positional aggregate whose elements it
        owns outright. Each element drops through `_emit_drop_at`, so a nested
        tuple, an optional element, a fixed-array element and a Deinit struct
        element all recurse.

        A tuple has no `deinit` method of its own and can never have one (it is
        a structural type, not a nameable one), so this is the whole story: the
        caller in `_emit_drop_at` reaches here directly, and a tuple nested in a
        struct field / enum payload / array element / coroutine frame slot
        reaches it through that container's own glue.
        """
        elements = self._tuple_elements(saw_type)
        i32 = ir.IntType(32)
        for idx in reversed(range(len(elements))):
            etype = elements[idx]
            if etype is None or not self._needs_cleanup(etype):
                continue
            elem_ptr = self.builder.gep(
                tuple_ptr, [ir.Constant(i32, 0), ir.Constant(i32, idx)],
                name=f"tup_drop_{idx}")
            self._emit_drop_at(elem_ptr, etype)

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
        saw_type = self._retag_enum(saw_type)
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
        if saw_type.kind == TypeKind.FUNCTION:
            # An escaping closure is ImplicitCopy (design 73): retaining bumps its
            # heap env's refcount (a null-env/non-owning closure is a no-op).
            self._emit_closure_retain_at(ptr)
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
        if saw_type.kind == TypeKind.TUPLE:
            self._emit_tuple_retain_at(ptr, saw_type)
            return
        self._emit_field_retain_at(ptr, saw_type)

    def _emit_tuple_retain_at(self, tuple_ptr, saw_type: SawType):
        """Bump every owning element of the tuple at `tuple_ptr` — the mirror of
        `_emit_tuple_cleanup_at`, in forward position order."""
        elements = self._tuple_elements(saw_type)
        i32 = ir.IntType(32)
        for idx, etype in enumerate(elements):
            if etype is None or not self._needs_cleanup(etype):
                continue
            elem_ptr = self.builder.gep(
                tuple_ptr, [ir.Constant(i32, 0), ir.Constant(i32, idx)],
                name=f"tup_retain_{idx}")
            self._emit_retain_at(elem_ptr, etype)

    def _emit_closure_retain_at(self, ptr):
        """Bump the refcount of the escaping closure stored at `ptr` (design 73).
        The closure value bytes are unchanged (the shared env pointer is aliased),
        so no store-back is needed — only the atomic increment."""
        closure_val = self.builder.load(ptr, name="closure_retain")
        if (not isinstance(closure_val.type, ir.LiteralStructType)
                or len(closure_val.type.elements) != 3):
            return
        env_ptr = self.builder.extract_value(closure_val, 1, name="retain_env")
        dtor_ptr = self.builder.extract_value(closure_val, 2, name="retain_dtor")
        self._emit_closure_env_retain(env_ptr, dtor_ptr)

    def _emit_closure_env_retain(self, env_ptr, dtor_ptr):
        """Atomic +1 on an escaping closure's env refcount word (design 73),
        guarded by a non-null dtor (a null-env / non-owning closure retains as a
        no-op). Mirrors String's monotonic retain."""
        word = self.int_type
        null_dtor = ir.Constant(dtor_ptr.type, None)
        has_dtor = self.builder.icmp_unsigned("!=", dtor_ptr, null_dtor,
                                              name="closure_has_dtor")
        with self.builder.if_then(has_dtor):
            rc_ptr = self.builder.bitcast(env_ptr, word.as_pointer(),
                                          name="env_rc_ptr")
            self.builder.atomic_rmw('add', rc_ptr, ir.Constant(word, 1),
                                    ordering='monotonic')

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

    def _emit_enum_deep_copy(self, value, saw_type: SawType):
        """Copy an enum VALUE payload-deep (design 139).

        The derived body behind `@synthesize extension E: ImplicitCopy {}` /
        `: ExplicitCopy {}`. The active variant is a runtime choice, so the copy
        switches on the tag and duplicates only that variant's payload fields,
        each through `_emit_copy_value` — which means every field copies at ITS
        own tier: a String payload retains, a `Vector<Int>` payload deep-copies,
        a trivial one is bitwise. A payload-free variant is a bare tag and copies
        as itself.

        Works through a temporary rather than an insert chain because the payload
        is a bitcast union: reaching a field means GEPping through a
        variant-shaped view of it, which needs an address.
        """
        key = self._enum_key(saw_type)
        if key is None:
            return value
        llvm_enum_type, variant_tags, variant_info = self.enum_types[key]
        if isinstance(llvm_enum_type, ir.IntType):
            # A payload-free enum is just its tag: bitwise.
            return value
        copy_variants = [
            name for name, fields in variant_info.items()
            if any(self._needs_cleanup(ftype) for _, ftype in fields)
        ]
        if not copy_variants:
            return value

        i32 = ir.IntType(32)
        tmp = self._entry_alloca(value.type, name="enum_cp_tmp")
        self.builder.store(value, tmp)
        tag_ptr = self.builder.gep(
            tmp, [ir.Constant(i32, 0), ir.Constant(i32, 0)], name="enum_cp_tag_ptr")
        tag = self.builder.load(tag_ptr, name="enum_cp_tag")
        func = self.builder.function
        cont_bb = func.append_basic_block("enum_cp_cont")
        switch = self.builder.switch(tag, cont_bb)
        variant_blocks = []
        for name in copy_variants:
            bb = func.append_basic_block(f"enum_cp_{name}")
            switch.add_case(ir.Constant(i32, variant_tags[name]), bb)
            variant_blocks.append((name, bb))
        for name, bb in variant_blocks:
            self.builder.position_at_end(bb)
            fields = variant_info[name]
            param_struct_type = ir.LiteralStructType(
                [self._get_llvm_type(ftype) for _, ftype in fields])
            payload_ptr = self.builder.gep(
                tmp, [ir.Constant(i32, 0), ir.Constant(i32, 1)],
                name="enum_cp_payload_ptr")
            struct_ptr = self.builder.bitcast(
                payload_ptr, ir.PointerType(param_struct_type),
                name="enum_cp_payload_struct")
            for idx in range(len(fields)):
                _, ftype = fields[idx]
                if not self._needs_cleanup(ftype):
                    continue
                field_ptr = self.builder.gep(
                    struct_ptr, [ir.Constant(i32, 0), ir.Constant(i32, idx)],
                    name="enum_cp_payload_field")
                original = self.builder.load(field_ptr, name="enum_cp_field")
                self.builder.store(self._emit_copy_value(original, ftype), field_ptr)
            self.builder.branch(cont_bb)
        self.builder.position_at_end(cont_bb)
        return self.builder.load(tmp, name="enum_cp_result")

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
        saw_type = self._retag_enum(saw_type)
        # ImplicitCopy leaf (String/Arc/user copy()): retain bumped it, so release
        # is its ordinary drop (refcount decrement).
        method_base = self._type_method_base(saw_type)
        if method_base is not None:
            copy_name = self._mangle_method_name(method_base, "copy")
            if self.functions.get(copy_name) is not None:
                self._emit_drop_at(ptr, saw_type)
                return
        if saw_type.kind == TypeKind.FUNCTION:
            # ImplicitCopy closure: release == drop (refcount decrement, teardown
            # at zero) — the exact inverse of `_emit_closure_retain_at` (design 73).
            self._emit_closure_drop_at(ptr, saw_type)
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
        if saw_type.kind == TypeKind.TUPLE:
            self._emit_tuple_release_at(ptr, saw_type)
            return
        self._emit_field_release_at(ptr, saw_type)

    def _emit_tuple_release_at(self, tuple_ptr, saw_type: SawType):
        """Release the tuple at `tuple_ptr` down to exactly what
        `_emit_tuple_retain_at` would have bumped, in reverse position order."""
        elements = self._tuple_elements(saw_type)
        i32 = ir.IntType(32)
        for idx in reversed(range(len(elements))):
            etype = elements[idx]
            if etype is None or not self._needs_cleanup(etype):
                continue
            elem_ptr = self.builder.gep(
                tuple_ptr, [ir.Constant(i32, 0), ir.Constant(i32, idx)],
                name=f"tup_release_{idx}")
            self._emit_release_at(elem_ptr, etype)

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

        # A tuple copies per element for the same reason an array does: it is a
        # positional aggregate that owns its parts, and design 139 gives it the
        # strongest element's tier. This has to land WITH the drop glue above —
        # a bitwise tuple copy beside a real element drop is one allocation and
        # two releases, which is the over-release half of DF-151f.
        if saw_type.kind == TypeKind.TUPLE:
            return self._emit_tuple_deep_copy(value, saw_type)

        # An escaping closure is ImplicitCopy (design 73): copying it bumps the
        # shared heap env's refcount and returns the same (aliased) value. A
        # null-env / non-owning closure retains as a no-op. Non-escaping closures
        # are borrows — bitwise, no retain. (The escaping bit is reliable here:
        # `saw_type` was already substituted through the monomorphization context
        # above, so a container element type carries it.)
        if (saw_type.kind == TypeKind.FUNCTION
                and getattr(saw_type, 'func_is_escaping', False)):
            if (isinstance(value.type, ir.LiteralStructType)
                    and len(value.type.elements) == 3):
                env_ptr = self.builder.extract_value(value, 1, name="copy_env")
                dtor_ptr = self.builder.extract_value(value, 2, name="copy_dtor")
                self._emit_closure_env_retain(env_ptr, dtor_ptr)
            return value

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

    def _transfer_type_for(self, value, dest_saw: SawType) -> SawType:
        """The SawType that actually describes `value` at a transfer whose
        DESTINATION is `dest_saw` (DF-151c).

        Retain and drop glue are both driven off the type they are HANDED, so
        that type must describe the value in hand. Every transfer site — a
        local, a field, an array element, a `&var` referent, a struct-literal
        field, a `let _` discard — has only the DESTINATION's type conveniently
        available, and at each of them the destination may be opt-encoded (`T?`)
        while the value is still the bare payload `T`: the optional wrap happens
        AFTER the copy, so a `T`-shaped value is what the glue sees. Driving it
        with `T?` walks Optional layout over a value that has no tag word — it
        reads a payload out of the payload itself and hands `T.copy`/`T.deinit`
        garbage (`i8* != i8` out of `_emit_optional_retain_at`). Unwrap to the
        payload in exactly the case the wrap will fire, so glue and wrap agree
        on what the value is.

        Keyed on the LLVM shape rather than on the source expression, for two
        reasons: it is the same test the wrap itself uses, and it holds for the
        synthesized nodes (coroutine frame stores) that carry no `resolved_type`
        to consult.

        "Same test as the wrap" is the load-bearing part, so it asks the question
        the way `_fit_optional_slot` now does: the value is the PAYLOAD when its
        LLVM type is the payload's. A bare shape test could not see that at a
        NESTED optional — an `Int?` value bound for an `Int??` destination is
        itself optional-shaped, so the glue was driven with `Int??` over a value
        that has one tag word, not two (DF-174b's family).
        """
        if (dest_saw is not None and dest_saw.is_optional()
                and dest_saw.inner_type is not None):
            inner_llvm = self._get_llvm_type(dest_saw.inner_type)
            if (value.type == inner_llvm
                    or not self._is_optional_type(value.type)):
                return dest_saw.inner_type
        return dest_saw

    def _generate_copy_for_dest(self, value, dest_saw: SawType):
        """Copy `value` for a transfer into a `dest_saw` destination — the
        `_generate_copy` every assignment/initialization site wants. See
        `_transfer_type_for` for why the destination's own type is not it."""
        return self._generate_copy(value, self._transfer_type_for(value, dest_saw))

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
        if saw_type.kind == TypeKind.TUPLE:
            return self._emit_tuple_deep_copy(value, saw_type)
        if saw_type.kind == TypeKind.OPTIONAL:
            return self._emit_optional_deep_copy(value, saw_type)
        if self.namespace.is_trivially_copyable(saw_type):
            return value
        method_base = self._type_method_base(saw_type)
        if method_base is not None:
            copy_name = self._mangle_method_name(method_base, "copy")
            fn = self.functions.get(copy_name)
            if fn is not None:
                return self.builder.call(fn, [value], name="elem_copy")
        # An aggregate with no copy() of its own but with OWNING fields — the
        # undeclared ImplicitCopy tier (design 159). `_generate_copy` has always
        # had this fallthrough; the per-ELEMENT path did not, so `[p; 3]` on a
        # `struct P { name: String }` would have splatted one String into three
        # slots with no retain and released it three times. Same recursive
        # retain, so an element's later drop is balanced.
        if (self._needs_cleanup(saw_type)
                and saw_type.kind in (TypeKind.STRUCT, TypeKind.ENUM)):
            return self._deep_copy_value(value, saw_type)
        # No copy path found: bitwise fallback (typechecker should have rejected).
        return value

    def _emit_optional_deep_copy(self, value, saw_type: SawType):
        """Copy an `Optional<T>` VALUE by copying its payload (design 139).

        None copies to None; Some copies to Some of the payload's own copy, so
        the tier the payload provides is the tier the optional provides —
        `String?` retains, `Vector<Int>?` deep-copies into an independent buffer,
        and a move-only payload never reaches here (the typechecker refuses
        `.copy()` on it).

        The payload copy is guarded by the tag rather than run unconditionally:
        the payload slot of a None holds uninitialized bytes, and handing those
        to `Vector.copy` would read a garbage pointer.
        """
        inner = saw_type.inner_type
        if inner is None or self.namespace.is_trivially_copyable(inner):
            # A trivial payload (and a None with nothing to copy) is bitwise —
            # no branch, no work.
            return value
        entry_bb = self.builder.block
        is_some = self.builder.extract_value(value, 0, name="opt_cp_is_some")
        func = self.builder.function
        some_bb = func.append_basic_block("opt_cp_some")
        cont_bb = func.append_basic_block("opt_cp_cont")
        self.builder.cbranch(is_some, some_bb, cont_bb)

        self.builder.position_at_end(some_bb)
        payload = self.builder.extract_value(value, 1, name="opt_cp_payload")
        payload_copy = self._emit_copy_value(payload, inner)
        copied = self.builder.insert_value(value, payload_copy, 1, name="opt_cp")
        # `_emit_copy_value` may itself have branched (a nested optional or
        # array), so the incoming edge is wherever the builder ended up.
        some_exit_bb = self.builder.block
        self.builder.branch(cont_bb)

        self.builder.position_at_end(cont_bb)
        result = self.builder.phi(value.type, name="opt_cp_result")
        result.add_incoming(value, entry_bb)
        result.add_incoming(copied, some_exit_bb)
        return result

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

    def _emit_tuple_deep_copy(self, value, saw_type: SawType):
        """Copy a tuple VALUE element by element, in position order (DF-151f).

        The exact counterpart of `_emit_array_deep_copy`: each element is
        duplicated through `_emit_copy_value`, so every element copies at ITS
        own tier — a String or `Arc` element retains, a `Vector<Int>` element
        deep-copies into an independent buffer, a trivial one is bitwise, and a
        nested tuple recurses. The result is a tuple whose eventual drop
        releases exactly the retains taken here.
        """
        elements = self._tuple_elements(saw_type)
        if not elements:
            return value
        result = value
        for idx, etype in enumerate(elements):
            if etype is None or self.namespace.is_trivially_copyable(etype):
                continue
            elem = self.builder.extract_value(value, idx, name=f"tup_cp_src{idx}")
            result = self.builder.insert_value(
                result, self._emit_copy_value(elem, etype), idx,
                name=f"tup_cp{idx}")
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
        elif getattr(value_expr, 'closure_lend', False):
            # An escaping closure LENT into a non-escaping (borrowing) slot (design
            # 73): the callee borrows and never drops it, so the caller KEEPS
            # ownership — do not clear its drop flag, or the env leaks. Pass the
            # value by value (a shared env pointer); the caller drops it once.
            pass
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
        # design 146: a place VALUE READ. Reading a place out as a value is
        # reading a CONTAINER SLOT the container still owns — the same
        # duplication `v[i]` and `obj.field` are, and it gets the same rule.
        # The lowering turns the read into a window closure returning its
        # parameter, so the read arrives here as a bare Identifier and the
        # container-slot arm below would never fire for it: an owning-but-
        # undeclared element (a `Path`, whose only field is a String) came out
        # as a bitwise alias, and the binding's drop freed the string the vector
        # still held.
        #
        # It also answers DF-146e rule 2. When the element type mentions a type
        # PARAMETER its tier is not knowable from the written type — only the
        # bounds are, and the use site already proved from them that every
        # instantiation can be copied. WHICH copy is a question for the
        # instantiation, which is where the matching DROP is emitted, so it is
        # answered here: `_generate_copy` substitutes the monomorphization
        # context and emits the concrete type's own copy.
        if getattr(value_expr, 'place_value_read', False):
            if getattr(value_expr, 'place_abstract_read', False):
                return True
            return self._slot_read_needs_copy(self._expr_type(value_expr))
        # design 124: a coroutine frame holds an across-suspend local in a
        # `T?`-encoded field and reads it as `self.name!`. The ForceUnwrap hides
        # the underlying field access from every check below (and from the
        # typechecker's transfer checkpoint), so such a transfer used to take a
        # non-retaining alias while the field kept its drop flag — the frame then
        # released the payload out from under the value it had handed on. The
        # frame keeps ownership of its field, so this read is a DUPLICATION,
        # exactly like `v[i]` / `obj.field` below; the `move` spelling of the same
        # read is not marked (it transfers the frame's own reference via
        # `__saw_forget` instead).
        if getattr(value_expr, 'frame_owning_read', False):
            return self._frame_read_needs_copy(value_expr)
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
                                   TypeKind.OPTIONAL, TypeKind.TUPLE)):
                return True
            # An escaping closure read out of a container slot (`buf[i]` inside
            # `Vector<() -> Int>.get`, a closure struct FIELD) is ImplicitCopy —
            # its env must be retained so the read-out copy's later drop is
            # balanced. Without this the shared env was freed twice (design 77
            # item 3 follow-up: a use-after-free at teardown). A bare Identifier
            # closure (a whole-binding move or a borrow-LEND) is NOT here — those
            # keep their existing move/lend handling.
            if (isinstance(value_expr, (ArrayIndex, MemberAccess, TupleIndex))
                    and t.kind == TypeKind.FUNCTION
                    and getattr(t, 'func_is_escaping', False)):
                return True
            return False
        return False

    def _slot_read_needs_copy(self, t: SawType) -> bool:
        """The container-slot rule, as a question about a TYPE.

        Reading a value out of storage its container keeps is a DUPLICATION —
        the two rules below are the `v[i]` / `obj.field` arms above, lifted so a
        place value read can ask them without being spelled as one of those
        nodes.
        """
        if t is None:
            return False
        if self.type_param_context:
            t = t.substitute(self.type_param_context)
        if self._get_cleanup_behavior(t) == "implicit_copy":
            return True
        if (self._needs_cleanup(t)
                and t.kind in (TypeKind.STRUCT, TypeKind.ENUM,
                               TypeKind.OPTIONAL, TypeKind.TUPLE)):
            return True
        return (t.kind == TypeKind.FUNCTION
                and bool(getattr(t, 'func_is_escaping', False)))

    def _frame_owning_read_copy(self, value_expr) -> bool:
        """True when `value_expr` is a design-124-marked frame-field read whose
        payload must be retained at an assignment site (the assignment paths
        decide the retain themselves rather than going through
        `_gen_transfer_value`)."""
        return (getattr(value_expr, 'frame_owning_read', False)
                and self._frame_read_needs_copy(value_expr))

    def _frame_read_needs_copy(self, value_expr) -> bool:
        """Whether a design-124-marked frame-field read must retain its payload.

        Mirrors the container-slot rules in `_transfer_needs_copy`, applied to the
        UNWRAPPED payload type: retain an ImplicitCopy value (`copy()` == a
        refcount bump), an owning aggregate, or an escaping closure env. A NoCopy
        payload is never duplicated — it can only leave the frame through an
        explicit `move`, which takes the `__saw_forget` path instead.

        An un-annotated node is left alone: some synthesized frame reads never
        pass the typechecker, and without a resolved type there is nothing to
        copy against — the pre-124 aliasing behavior is what the rest of the
        pipeline already expects there."""
        if getattr(value_expr, 'resolved_type', None) is None:
            return False
        t = self._expr_type(value_expr)
        if t is None:
            return False
        if self.type_param_context:
            t = t.substitute(self.type_param_context)
        behavior = self._get_cleanup_behavior(t)
        if behavior == "no_copy":
            return False
        if behavior == "implicit_copy":
            return True
        if t.kind == TypeKind.FUNCTION and getattr(t, 'func_is_escaping', False):
            return True
        # TUPLE belongs on this list for the same reason the others do, and its
        # absence is what made DF-151f's fix crash before it landed: an owning
        # tuple read out of a coroutine frame slot took a non-retaining alias
        # while the frame kept its own reference, so the new drop glue released
        # the same `Arc` twice. There is no `_get_cleanup_behavior` answer for a
        # tuple to catch it earlier — a structural type has no name to look a
        # conformance up under — so this kind list is the whole decision.
        return (self._needs_cleanup(t)
                and t.kind in (TypeKind.STRUCT, TypeKind.ENUM,
                               TypeKind.OPTIONAL, TypeKind.TUPLE))

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
        # A field type is copy-on-init when it implements ImplicitCopy — OR when
        # it is an aggregate with no whole-type copy() that still OWNS
        # cleanup-needing payloads (an `Optional<String>`, an owning-payload
        # tuple/struct/enum): initializing such a field from an existing binding
        # is a DUPLICATION, and without the recursive retain the stored copy
        # aliases the binding's buffers, which the binding's scope-exit release
        # then frees under the aggregate (DF-116a use-after-free).
        # `_generate_copy` dispatches these to `_deep_copy_value`. NoCopy and
        # ExplicitCopy sources never reach here as bare identifiers (the
        # typechecker forces `move`/`.copy()` first).
        behavior = self._get_cleanup_behavior(field_type)
        if behavior != "implicit_copy" and not (
                behavior != "no_copy" and self._needs_cleanup(field_type)):
            return False

        # Check if the value comes from an existing binding that needs copying

        if isinstance(value_expr, MoveExpr):
            # Move expressions transfer ownership, no copy needed
            return False

        # design 124: a frame-field read (`self.name!`) initializing a struct
        # field is the same duplication a `MemberAccess` source is — see
        # `_transfer_needs_copy`. Without this a `Wrap(s: s)` built in a driven
        # body aliased the frame's `s`, which eager teardown then freed.
        if getattr(value_expr, 'frame_owning_read', False):
            return self._frame_read_needs_copy(value_expr)

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
        flag = self._entry_alloca(ir.IntType(1), name=f"{var_name}.dropflag")
        self.builder.store(ir.Constant(ir.IntType(1), 1), flag)
        self.drop_flags[var_name] = flag
        # Capture the binding's storage + drop flag NOW (design 100). A later
        # inner binding may SHADOW this name in `self.variables`/`self.drop_flags`;
        # resolving by name at scope-exit would then clean up the WRONG (inner,
        # already-freed) storage — a double-free. The captured pointers pin this
        # exact binding regardless of subsequent shadowing.
        var_ptr = self.variables.get(var_name)
        self.cleanup_stack[-1].append((var_name, saw_type, var_ptr, flag))

    def _cleanup_scope(self, scope_vars):
        """Generate cleanup code for all variables in a scope.

        Variables are cleaned up in reverse declaration order to ensure
        proper destruction semantics (LIFO). A binding with a runtime drop flag
        (registered via `_register_cleanup`) is dropped only if its flag is still
        set — correct under conditional moves. A binding without a flag (e.g. a
        statement-scoped temporary, never a `move` target) uses the static
        `moved_variables` skip.

        Each entry pins the binding's captured storage + flag (design 100), so a
        shadowing inner binding of the same name can never redirect this cleanup
        to the wrong storage.
        """
        for entry in reversed(scope_vars):
            self._emit_scope_var_drop(*entry)

    def _emit_scope_var_drop(self, var_name, saw_type, var_ptr, flag):
        """Drop one registered scope binding, honoring its runtime drop flag.

        Shared by `_cleanup_scope` (scope exit) and the design-107 same-scope
        redefinition drop. A flagged binding drops only if its flag is still set
        (`if flag { deinit }`) — correct under conditional moves; an unflagged
        one uses the static `moved_variables` skip."""
        if var_ptr is None:
            # No captured storage (guard-let with no fresh temporary): fall
            # back to a by-name resolution for compatibility.
            var_ptr = self.variables.get(var_name)
            if var_ptr is None:
                return
        if flag is not None:
            # Guard the drop on the runtime flag: `if flag { deinit }`.
            needs = self.builder.load(flag, name=f"{var_name}.needsdrop")
            drop_bb = self.builder.function.append_basic_block(
                name=f"drop.{var_name}")
            cont_bb = self.builder.function.append_basic_block(
                name=f"drop.{var_name}.cont")
            self.builder.cbranch(needs, drop_bb, cont_bb)
            self.builder.position_at_start(drop_bb)
            self._emit_drop_at(var_ptr, saw_type)
            if not self.builder.block.is_terminated:
                self.builder.branch(cont_bb)
            self.builder.position_at_start(cont_bb)
            return
        # No drop flag: fall back to the static moved-variable skip.
        if var_name in self.moved_variables:
            return
        self._emit_drop_at(var_ptr, saw_type)

    def _drop_redefined_same_scope(self, var_name: str):
        """Design 107: a DERIVED same-scope redefinition (`var d = read();
        let d = parse(move d)` / `let d = d.copy()`) REPLACES the old binding.
        If the old binding still OWNS a value here — a `.copy()`-style
        derivation — drop it at THIS point, deterministically; a `move`-style
        derivation already cleared its drop flag, so the guarded drop is a
        no-op. Its scope-exit cleanup entry is retired either way, so the old
        storage is never dropped twice.

        Detection is precise: an entry for `var_name` in the INNERMOST cleanup
        scope means a prior owning binding of this name in the same lexical
        scope (an enclosing-scope shadow lives in an OUTER frame and keeps
        living). Called after the initializer is generated (so `move` has
        settled the flag) and before the replacing binding is registered."""
        if not self.cleanup_stack:
            return
        current = self.cleanup_stack[-1]
        idx = None
        for i, entry in enumerate(current):
            if entry[0] == var_name:
                idx = i  # the most recent same-scope owning binding
        if idx is None:
            return
        _, saw_type, var_ptr, flag = current.pop(idx)
        # The replacing binding starts fresh; clear any moved-from mark so a
        # later reuse of the name is not mistaken for the retired binding.
        self.moved_variables.discard(var_name)
        self._emit_scope_var_drop(var_name, saw_type, var_ptr, flag)

    def _cleanup_all_scopes(self):
        """Generate cleanup code for all scopes (for early return).

        Called before return statements to ensure all in-scope variables
        are properly cleaned up.
        """
        for scope_vars in reversed(self.cleanup_stack):
            self._cleanup_scope(scope_vars)

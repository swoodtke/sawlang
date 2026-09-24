"""
Resource management utilities for the Saw code generator.

This module provides mixin methods for handling resource cleanup, including:
- Determining cleanup behavior for types (Deinit, Copy, NoCopy)
- Generating deinit calls for proper destruction
- Generating copy calls for Copy types
- Managing scope-based cleanup for deterministic resource management

Usage:
    class CodeGenerator(ResourcesMixin, ...):
        pass
"""

from typing import Optional, List
from llvmlite import ir
from ast_nodes import (SawType, TypeKind, MoveExpr, Identifier, MemberAccess,
                       ArrayIndex, TupleIndex, SelfExpr,
                       FunctionCall, MethodCall, EnumInit,
                       TupleLiteral, ArrayLiteral, MapLiteral, SetLiteral,
                       Expression, ForLoop,
                       PRIMITIVE_EXT_KINDS)
from .mangle import mangle_type


class ResourcesMixin:
    """Mixin providing resource management methods for CodeGenerator.

    Methods:
        _get_type_name_for_conformance: Get canonical name for interface lookup
        _get_cleanup_behavior: Determine how a type should be cleaned up
        _needs_cleanup: Check if a type requires cleanup
        _generate_deinit_call: Generate deinit() call for a variable
        _generate_copy: Generate copy() call for Copy types
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
            # String is a compiler-known Copy + Deinit type.
            return "String"
        if saw_type.kind == TypeKind.STRUCT:
            return saw_type.struct_name
        elif saw_type.kind == TypeKind.ENUM:
            return saw_type.enum_name
        return None

    # Every primitive pseudo-struct an extension may be written on, and the
    # `SawType` kind its `self` carries. This is the one table in
    # `ast_nodes.PRIMITIVE_EXT_KINDS`, not a copy of it.
    _PRIMITIVE_EXT_KINDS = PRIMITIVE_EXT_KINDS

    def _primitive_ext_name(self, saw_type):
        """The pseudo-struct name a primitive receiver dispatches under, or None.

        Named from the stamped `SawType`, never from the LLVM shape: an `Int` is
        an i64 and so is an `Int64` and a `UInt`, and a payload-free enum is an
        i32 like an `Int32`.
        """
        if saw_type is None:
            return None
        for name, kind in self._PRIMITIVE_EXT_KINDS.items():
            if saw_type.kind == kind:
                return name
        return None

    def _primitive_self_llvm_type(self, struct_name: str):
        """The LLVM `self` type for a method in an extension on a primitive
        pseudo-struct, or None for an ordinary struct. String is i8*; the
        integers are their own widths; Float is a double."""
        kind = self._PRIMITIVE_EXT_KINDS.get(struct_name)
        if kind is None:
            return None
        return self._get_llvm_type(SawType(kind))

    def _enum_tag_llvm_type(self, enum_name: str):
        """The LLVM integer type of an enum's tag.

        `i32` for every ordinary enum. A raw-backed enum is exactly its declared
        backing width, because the backing pins the representation: `enum E:
        UInt8` is one byte, which is what makes it legal as a field of an
        `UnsafeMemory`-viewed wire struct (design 145)."""
        entry = self.enum_types.get(enum_name)
        if entry is None:
            return ir.IntType(32)
        llvm_type = entry[0]
        if isinstance(llvm_type, ir.IntType):
            return llvm_type
        # Payload shape `{ tag, [M x iK] }`.
        return llvm_type.elements[0]

    def _ext_self_types(self, type_name: str):
        """The `(llvm_type, saw_type)` pair for `self` in `extension <type_name>`.

        One place that knows all three receiver shapes: a primitive
        pseudo-struct, an enum (a bare tag when payload-free, or
        `{tag, [M x iK]}` with payloads), and an ordinary struct. Getting the
        SawType kind right matters as much as the LLVM type: a STRUCT-kinded
        `self` on an enum has no variants, so every `match self` in the body
        would fail to resolve its cases."""
        prim = self._primitive_self_llvm_type(type_name)
        if prim is not None:
            return prim, SawType(self._PRIMITIVE_EXT_KINDS[type_name])
        if type_name in self.enum_types:
            return (self.enum_types[type_name][0],
                    SawType(TypeKind.ENUM, enum_name=type_name))
        return (self.struct_types[type_name][0],
                SawType(TypeKind.STRUCT, struct_name=type_name))

    def _type_method_base(self, saw_type: SawType) -> Optional[str]:
        """Base symbol for a type's compiler-invoked methods (deinit / copy).

        This must match the name the method was registered under. Monomorphized
        methods are registered as `mangle_method(mangle_named(base, args), m)`
        (e.g. `Box<Int>.deinit` -> `Box$1$Int_deinit`), so the base here is the
        canonical `mangle_type` of the (struct/enum) type. String's compiler-
        provided methods use the base 'String'. Non-generic types mangle to
        their plain name.

        Default type arguments are filled first. A field written `Vector<Int>`
        denotes `Vector<Int, GlobalAllocator>`, and the monomorphized methods
        are registered under that full form
        (`Vector$2$Int$GlobalAllocator_deinit`). A consumer that misses its
        method takes its own fallback (the drop path structural glue, the
        copy/retain paths a structural or trivial copy), so mangling the
        written form would silently skip the type's own method: for `deinit`
        its elements leak and its buffer is never freed. This lookup therefore
        fills defaults through `_fill_default_type_args` (design 37); plain
        `mangle_type` does not.
        """
        # Primitive pseudo-structs carrying method extensions.
        for _name, _kind in self._PRIMITIVE_EXT_KINDS.items():
            if saw_type.kind == _kind:
                return _name
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
        - 'implicit_copy': Type implements Copy, call copy() on copy
        - 'no_copy': Type implements NoCopy, cannot be copied

        Results are cached in self.type_cleanup_behavior. The cache key carries
        the type arguments, because one of the answers below is structural: a
        generic enum's tier comes from its instantiated payloads, so `Slot<K>`
        and `Slot<Res>` are two different answers under one base name. Keyed
        on the base name alone, whichever was seen first would decide for both;
        the abstract form answers "none", so a concrete `Slot<Res>` read would
        emit no copy and be over-released.
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
        elif self.namespace.names_copy_tier(conformances):
            behavior = "implicit_copy"
        elif self.namespace.is_structurally_implicit_copy(saw_type):
            # The undeclared Copy tier, structs and enums alike. An enum
            # cannot declare Copy at all, so an owning-payload enum
            # (`DepSource { PathDep(String) }`) is classified here. A struct
            # whose owning members are all trivial/Copy (`struct P { name:
            # String }`, a struct holding a closure) is on the same footing:
            # the containment checks exempt it from declaring a policy, so the
            # tier is automatic and this is the only place that can report it.
            # Answering "none" would make a copy emit no retain while the
            # per-binding drop still releases every field (design 159).
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
        re-resolved it (the parser cannot know which it is, and not every path
        canonicalizes). A struct field is the case that matters:
        `namespace.get_struct_fields` hands back the raw parsed annotation, so
        `struct Holder { slot: Slot }` describes its enum field as a struct.

        Every value-lifecycle dispatch below is keyed on `kind`, so a
        mis-tagged type falls off the end of the chain and emits nothing: no
        drop, no retain, no release, and the enum's payload leaks.
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
        Copy / ExplicitCopy) OR -- even with no declared conformance --
        it transitively holds a value needing cleanup:
        - a struct with a cleanup-needing field;
        - an enum any of whose variants carries a cleanup-needing payload
          field. Enums dodge the containment rules entirely, so this test is
          what makes an undeclared enum holding a Deinit payload get its active
          variant released at scope exit;
        - an `Optional<T>` whose inner `T` needs cleanup;
        - a fixed array or tuple whose elements do, and an escaping closure.
        """
        # `Box<any Trait, A>` always owns a heap payload: its erased teardown
        # (vtable destructor + dealloc) must run at scope death.
        if self._is_erased_box(saw_type):
            return True
        # Left tagged STRUCT this would fall to the struct-field path below,
        # which finds no fields and poisons the shared cache under the bare name
        # with `False`; `_enum_needs_variant_cleanup` would then read that stale
        # `False` and treat an owning enum payload (an `Arc` inside a
        # `Vector<enum>` slot) as non-owning: no drop glue and no retain.
        saw_type = self._retag_enum(saw_type)
        if self._get_cleanup_behavior(saw_type) != "none":
            return True
        # An escaping closure value (design 71) is an owning value: it may carry a
        # heap environment whose destructor releases owned captures and frees the
        # block. Its drop glue null-checks the value's carried dtor pointer, so a
        # non-owning closure (no captures / borrow-only) is a safe no-op. A
        # non-escaping closure borrows the enclosing frame and owns nothing.
        if saw_type.kind == TypeKind.FUNCTION:
            return bool(saw_type.func_is_escaping)
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
            # A tuple owns its elements exactly as a struct owns its fields (a
            # composite takes its strongest element's tier), so it needs
            # cleanup iff any element does. Named tuples included: the names
            # are a projection convenience, not a different type. Without this
            # arm a tuple falls to the struct-field path, which finds no
            # fields, and a `(Arc<Res>, Int)` local leaks silently (design 139).
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

        A value nobody holds must be registered as a statement-scoped
        temporary, or nothing will ever release it. A value an existing binding
        does hold must not be, or its owner's cleanup and this one both run --
        a double free. So this is an ownership question with two wrong answers,
        and it is the producer question design 269 made total: "does this
        expression name storage an existing owner keeps, or mint a value the
        reader owns?"

        The answer is the checker's, not codegen's: `typechecker.producers`
        classifies every node class, and its gate fails the build when one is
        unclassified, so a new expression form cannot silently leak here. A
        second, independent codegen list would answer False for any node it
        forgot, and that value would leak.

        The mapping, one line per kind:

          READS     -- storage an existing owner keeps. NOT a temporary; its
                       binding runs the cleanup.
          PROJECTS  -- a PART of another expression's storage (`o!`, `try r`, a
                       forwarding cast). The owner of the operand is the owner
                       of the part, so recurse -- EXCEPT when the extraction
                       itself minted a reference, which design 131 records as
                       `payload_needs_copy` and which makes the payload the
                       reader's own.
          REWRAPS   -- the same value under a wider type; recurse to the
                       operand, which is the value that actually transferred.
          BRANCHES  -- every arm is a transfer into the merged home, so the
                       merged value is the reader's whichever arm ran: a fresh
                       arm hands over a temporary, and an arm that READS a
                       binding retains at the arm. Both owe a release here.
          BUILDS    -- a fresh value, including the aggregate literals: each
                       builds its elements through `_gen_transfer_value` and
                       so holds references it took itself.
          OWN_ARM   -- `move x` retires the source binding, so nobody else will
                       release the value; `&x` grants no ownership at all.

        Entry points (the positions that consume a value without binding it):
          `_generate_member_access` (structs.py) -- a member-access object
          `_generate_method_call` (calls.py) -- a method-call receiver
          `_generate_optional_presence` (calls.py) -- an `is_some`/`is_none` receiver
          `visit_ExpressionStatement` (statements.py) -- an expression statement
          `_optional_source_hands_over` (conditionals.py) -- an `if let`/`guard let` scrutinee
          `_generate_match_expr` (match.py) -- a `match` scrutinee
          `_generate_match_general` (match.py) -- a `match` scrutinee
        """
        # The typechecker/codegen seam is crossed function-locally, as
        # `typechecker`'s own `from codegen.mangle import ...` calls do. The
        # module is a pure classification over node-local annotations (no
        # state, no scope), so asking it here answers the same question the
        # checkpoint asked, about the same node.
        from typechecker import producers
        from .calls import PreparedValue

        # Codegen's own synthesized nodes are codegen's to answer for. The
        # taxonomy's universe is the authored tree (`ast_nodes`' `Expression`
        # subclasses, which its gate enumerates); codegen declares `Expression`
        # subclasses no gate has seen, so each is answered here, by name, with
        # its reason. Anything else still reaches the taxonomy and is still
        # loud when unclassified (design 269).
        #
        # `PreparedValue` wraps an LLVM value its builder already owns (a stack
        # `StringBuilder` for `format(into:)`, a rendered error), so its
        # lifetime is that builder's and a release here would be a second one.
        if isinstance(expr, PreparedValue):
            return False

        node = expr
        depth = 0
        while node is not None:
            # A transparency chain is a handful of nodes deep at most; the
            # bound is a guard against a malformed tree, never a real limit.
            depth += 1
            if depth > 64:
                return False
            if not isinstance(node, (Expression, ForLoop)):
                return False
            kind = producers.producer_kind(node)
            if kind == producers.READS:
                return False
            if kind == producers.PROJECTS:
                # A Copy-tier payload duplicated at the extraction is a fresh
                # reference this position owns. Without the stamp the
                # extraction is a borrow of the operand's storage, so the
                # operand's owner answers.
                if getattr(node, 'payload_needs_copy', False):
                    return True
                node = producers.projected_operand(node)
                continue
            if kind == producers.REWRAPS:
                node = producers.rewrapped_operand(node)
                continue
            if kind == producers.OWN_ARM:
                return isinstance(node, MoveExpr)
            return True
        # A wrap around no value at all (a bare `return` in a
        # `Result<Void, E>` body) transfers nothing and owns nothing.
        return False

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
        binding that was moved out no longer owns anything, and `var x = ...;
        sink.push(move x); x = fresh` is the language's own revival idiom. The
        `move` transferred the value to the vector, so an unguarded drop at the
        reassignment would free what the vector holds.
        """
        var_ptr = self.variables.get(var_name)
        if var_ptr is None:
            return
        self._emit_scope_var_drop(var_name, saw_type, var_ptr,
                                  self.drop_flags.get(var_name))

    def _revive_assigned_binding(self, var_name: str, saw_type: SawType):
        """A moved `var` revives on reassignment, so it owns again.

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
                # `deinit` is `&var self` by construction, so the funnel is a
                # no-op here; routed through it so no receiver site re-decides.
                self.builder.call(fn, [self._self_operand(fn, ptr, name="deinit_self")])
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
        Copy over a refcounted heap env: dropping RELEASES one reference —
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
            # Over-release detector (mirrors __saw_string_release): old at or
            # below zero is a refcount underflow — panic deterministically
            # instead of leaving detection to the platform allocator.
            is_under = self.builder.icmp_signed("<", old, ir.Constant(word, 1),
                                                name="env_over_release")
            with self.builder.if_then(is_under):
                or_ptr, or_len = self._raw_bytes_ptr(
                    "panic: over-release of a closure environment "
                    "(refcount underflow)\n")
                self.builder.call(self.functions["__saw_rt_panic"],
                                  [or_ptr, or_len])
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

    def _emit_field_cleanup_at(self, struct_ptr, saw_type: SawType,
                               skip_fields=()):
        """Release every cleanup-needing field of the struct at `struct_ptr`, in
        reverse field order (LIFO). Each field is dropped through `_emit_drop_at`
        so nested structs recurse and String/Deinit fields hit their release.

        This is the field half of drop glue: it never invokes the struct's OWN
        deinit (the caller already did, or there is none), only its fields.

        `skip_fields` (design 260 §3) names fields a consuming body MOVED OUT:
        their values left with the move and are released once, by their new
        owner, wherever they went. Reverse declaration order holds among the
        fields that remain.
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
            if field_name in skip_fields:
                continue
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
        at `enum_ptr`, by switching on the runtime tag.

        The enum is laid out `{ i32 tag, [M x iK] payload }`. For each variant
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
        """Release the payload of an `Optional<T>` at `opt_ptr` when present.
        Optionals are `{ i1 is_some, T }`: branch on the flag and
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

    # ===== Copy-with-retain glue (design 65) =====
    #
    # The exact mirror of the drop glue above. `_emit_drop_at` releases an owning
    # value's refcounts; `_emit_retain_at` bumps them, in place, so a bitwise
    # duplicate of an aggregate becomes a genuinely-owned independent copy whose
    # eventual drop is balanced. Used to copy-with-retain a struct/enum read out
    # of a container it stays in (e.g. a `Vector` slot via `.get()`): the whole
    # value is not a clean Copy (it may be a NoCopy enum like `MapSlot`),
    # but its owning fields (String/Arc/nested owners) must each be retained so
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
        # A leaf with its own copy() (Copy String/Arc/user type): retain
        # in place — copy() bumps the refcount and returns the (same-buffer)
        # value, which we store back.
        method_base = self._type_method_base(saw_type)
        if method_base is not None:
            copy_name = self._mangle_method_name(method_base, "copy")
            fn = self.functions.get(copy_name)
            if fn is not None:
                # The receiver's shape is the callee's to declare:
                # `_self_operand` passes the loaded value to a by-value `copy`
                # and spills it to a fresh slot for a by-pointer one
                # (design 261).
                v = self.builder.load(ptr, name="retain_leaf")
                v2 = self.builder.call(
                    fn, [self._self_operand(fn, v, name="retain_self")],
                    name="retain_bump")
                self.builder.store(v2, ptr)
                return
        if saw_type.kind == TypeKind.FUNCTION:
            # An escaping closure is Copy (design 73): retaining bumps its
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
        """Copy an enum value payload-deep (design 139).

        The derived body behind `@synthesize extension E: Copy {}` /
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
    # Releases the value at `ptr` down to exactly what `_emit_retain_at` would
    # have retained: only refcounted (Copy) leaves and the owning fields
    # reachable through them. It does NOT run the deinit of a
    # NoCopy-with-side-effect leaf (a `Deinit` struct that carries no refcount,
    # e.g. a `Val { id: Int }` counter): retain never bumped it, so release must
    # not fire it. This lets an owning payload field discarded with `_` in a
    # probe match release a retained String/Arc without over-counting a
    # non-refcounted `Deinit` value (design 65).

    def _emit_release_at(self, ptr, saw_type: SawType):
        if not self._needs_cleanup(saw_type):
            return
        saw_type = self._retag_enum(saw_type)
        # Copy leaf (String/Arc/user copy()): retain bumped it, so release
        # is its ordinary drop (refcount decrement).
        method_base = self._type_method_base(saw_type)
        if method_base is not None:
            copy_name = self._mangle_method_name(method_base, "copy")
            if self.functions.get(copy_name) is not None:
                self._emit_drop_at(ptr, saw_type)
                return
        if saw_type.kind == TypeKind.FUNCTION:
            # Copy closure: release == drop (refcount decrement, teardown
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
        """Generate a copy of a value, calling copy() for Copy types.

        Returns the copied value (which may be the original for non-Copy types).

        For Copy types, calls the copy(self) -> Self method.
        For regular types, returns the original value (bitwise copy).
        For NoCopy types, raises an error (should be caught by typechecker).
        """
        # A fixed array `[T; N]` copies per element (design 33). Only reached
        # implicitly for Copy-element arrays (trivial arrays need no
        # copy; ExplicitCopy/NoCopy arrays are move-gated by the typechecker).
        # Resolve a generic type to the active monomorphization so the recursive
        # retain glue below can look up the concrete struct/enum layout.
        if self.type_param_context:
            saw_type = saw_type.substitute(self.type_param_context)

        # Everything below the substitution is `_emit_copy_value`'s, and this is
        # one of its named entry points: the transfer site's only extra job is
        # resolving the type to the active monomorphization, so the funnel's
        # own arms can look up the concrete struct/enum layout. A second arm
        # list here would drift from the funnel's (design 271).
        return self._emit_copy_value(value, saw_type)

    def _transfer_type_for(self, value, dest_saw: SawType) -> SawType:
        """The SawType that actually describes `value` at a transfer whose
        destination is `dest_saw`.

        Retain and drop glue are both driven off the type they are handed, so
        that type must describe the value in hand. Every transfer site has only
        the destination's type available, and the destination may be `T?`
        while the value is still the bare payload `T`: the optional wrap happens
        after the copy. Driving the glue with `T?` walks Optional layout over a
        value with no tag word. So unwrap to the payload in exactly the case
        the wrap will fire.

        Keyed on the LLVM shape, as `_fit_optional_slot` is, because that is
        the wrap's own test and it holds for synthesized nodes (coroutine frame
        stores) with no `resolved_type`. The value is the payload when its LLVM
        type is the payload's; a bare "is it optional-shaped" test would
        misread an `Int?` value bound for an `Int??` destination.
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
        """The copy-emission funnel: an independent copy of a value of
        `saw_type`, at that type's own copy tier (design 271).

        A caller that keeps its own arm list re-implements this one
        incompletely and falls through to a bitwise copy for what it missed;
        an automatic Copy-tier aggregate (members all trivial/Copy, no declared
        policy) then aliases its `String` fields and is released twice.

        Entry points:
          `_generate_copy` -- every transfer site marked `needs_copy`
          `_emit_array_deep_copy` -- per-element recursion
          `_emit_tuple_deep_copy` -- per-element recursion
          `_emit_optional_deep_copy` -- payload recursion
          `_emit_enum_deep_copy` -- per-payload-field recursion
          `calls._generate_method_call` -- a source `.copy()` with no emitted `copy` symbol
          `methods._generate_derived_copy_body` -- a `@synthesize`d memberwise `copy()`
          `closures._generate_closure` -- a `[copy x]` capture
          `operators._retain_comparison_operand` -- a String comparison's `other`

        The arms, in order:
        1. Array / tuple / optional: recurse per element so every element
           copies at its own tier.
        2. An escaping closure: Copy over a refcounted heap env; the value
           bytes are unchanged, only the env refcount moves.
        3. A real `copy` symbol (String, Arc, a declared Copy/ExplicitCopy
           conformance, a hand-written hook), asked before the trivial test
           because a hand-written `copy()` on a POD receiver must run.
        4. Trivially copyable: bitwise.
        5. An aggregate with no `copy` of its own that still owns
           cleanup-needing members: `_deep_copy_value` retains each through
           `_emit_retain_at`, the mirror of the drop glue (design 159).
        6. A leaf with nothing to retain: bitwise.

        A type that cannot be duplicated never reaches here: the typechecker
        refuses it.
        """
        if saw_type.kind == TypeKind.ARRAY:
            return self._emit_array_deep_copy(value, saw_type)
        if saw_type.kind == TypeKind.TUPLE:
            return self._emit_tuple_deep_copy(value, saw_type)
        if saw_type.kind == TypeKind.OPTIONAL:
            return self._emit_optional_deep_copy(value, saw_type)
        # An escaping closure is Copy (design 73): duplicating it bumps the
        # shared heap env's refcount and returns the same (aliased) value, so
        # the duplicate and the original each release exactly once. A null-env /
        # non-owning closure retains as a no-op; a non-escaping closure is a
        # borrow and is bitwise.
        if saw_type.kind == TypeKind.FUNCTION:
            if (saw_type.func_is_escaping
                    and isinstance(value.type, ir.LiteralStructType)
                    and len(value.type.elements) == 3):
                env_ptr = self.builder.extract_value(value, 1, name="copy_env")
                dtor_ptr = self.builder.extract_value(value, 2, name="copy_dtor")
                self._emit_closure_env_retain(env_ptr, dtor_ptr)
            return value
        method_base = self._type_method_base(saw_type)
        if method_base is not None:
            copy_name = self._mangle_method_name(method_base, "copy")
            fn = self.functions.get(copy_name)
            if fn is not None:
                return self.builder.call(
                    fn, [self._self_operand(fn, value, name="elem_copy_self")],
                    name="elem_copy")
        if self.namespace.is_trivially_copyable(saw_type):
            return value
        # An aggregate with no copy() of its own but with owning members: the
        # undeclared Copy tier (design 159). `[p; 3]` on a
        # `struct P { name: String }` would otherwise splat one String into
        # three slots with no retain and release it three times.
        if (self._needs_cleanup(saw_type)
                and saw_type.kind in (TypeKind.STRUCT, TypeKind.ENUM)):
            return self._deep_copy_value(value, saw_type)
        # No copy path found: bitwise fallback (typechecker should have rejected).
        return value

    def _emit_optional_deep_copy(self, value, saw_type: SawType):
        """Copy an `Optional<T>` value by copying its payload (design 139).

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
        ExplicitCopy/Copy element runs its own `copy()` and the result is
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
        """Copy a tuple value element by element, in position order.

        The counterpart of `_emit_array_deep_copy`: each element is
        duplicated through `_emit_copy_value`, so every element copies at its
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

    def _gen_transfer_value(self, value_expr, *, apply_optional_wrap=True):
        """Generate a value being transferred into a new home (call argument,
        return value, aggregate element), honoring the typechecker's
        `needs_copy` annotation.

        The value-transfer checkpoint marks `expr.needs_copy = True` on any
        Copy value read out of an existing binding, so codegen invokes
        `copy()` uniformly at every transfer site instead of re-deciding per
        site; `_transfer_needs_copy` re-derives only the cases the checker
        records no decision for. `_generate_copy` runs at most once per
        transfer.

        A transfer into a block that is already terminated produces nothing.
        This is where an argument list meets a diverging earlier argument:
        once `die(1)` in `takes(1, die(1), x + y)` has written the block's
        `unreachable`, the third argument has nowhere to emit, and emitting
        into a terminated block is invalid IR. Asking here rather than in each
        argument loop makes the rule hold for every call shape and for the
        other transfer homes (an aggregate element, a return value)
        (design 228).
        """
        if self.builder is not None and self.builder.block.is_terminated:
            return None
        # Erase `&concrete` to `&any Trait` at the call boundary. The
        # typechecker tagged this argument; the underlying expression lowers to a
        # pointer to the concrete value, which we wrap into a fat pointer with the
        # (concrete, trait) vtable attached. A borrow — no move/copy (design 51).
        erase_trait = getattr(value_expr, 'erase_to_trait', None)
        if erase_trait is not None:
            data_ptr = self._generate_expression(value_expr)
            return self._erase_pointer_to_any(
                data_ptr, value_expr.erase_concrete, erase_trait)

        staged_struct = None
        if getattr(value_expr, "materialize_for_transfer", False):
            staged_struct = self._as_memberwise_struct_init(value_expr)
        if staged_struct is not None:
            # A by-value adapter with an actual memory home. Build both the
            # memberwise value and its checked Optional/Result transfer
            # wrappers there; returning the staged load directly avoids wrapping
            # the same annotations a second time below (SL-350).
            value = self._materialize_struct_value(
                value_expr, name="transfer.init",
                apply_optional_wrap=apply_optional_wrap)
            if value is None and self.builder.block.is_terminated:
                return None
            return value
        value = self._generate_expression(value_expr)
        if value is None and self.builder.block.is_terminated:
            return None
        if self._transfer_needs_copy(value_expr):
            value = self._generate_copy(value, self._expr_type(value_expr))
            # A copied/retained value wrapped into an optional parameter: the
            # Some(...) owns the fresh reference.
            return self._maybe_autowrap_optional(
                value_expr, value, apply_optional_wrap=apply_optional_wrap)
        elif getattr(value_expr, 'closure_lend', False):
            # An escaping closure lent into a non-escaping (borrowing) slot: the
            # callee borrows and never drops it, so the caller keeps ownership.
            # Clearing its drop flag would leak the env. Pass the value by value
            # (a shared env pointer); the caller drops it once (design 73).
            pass
        elif isinstance(value_expr, Identifier):
            # No copy/retain was needed, yet the value is being transferred into a
            # new home: for a named owned (ExplicitCopy/NoCopy) binding that means
            # its ownership is moving out (e.g. a tail-return `result` or
            # `return v` written without an explicit `move`, which the language
            # permits). The source must therefore not be dropped at scope exit:
            # clear its drop flag (design 42) and mark it moved for the unflagged
            # fallback path. A Copy source took the `needs_copy` branch
            # above (retain — the source stays live), so it never reaches here.
            name = value_expr.name
            flag = self.drop_flags.get(name)
            if flag is not None:
                self.builder.store(ir.Constant(ir.IntType(1), 0), flag)
            self.moved_variables.add(name)
        return self._maybe_autowrap_optional(
            value_expr, value, apply_optional_wrap=apply_optional_wrap)

    def _maybe_autowrap_optional(self, value_expr, value,
                                 *, apply_optional_wrap=True):
        """Build the call-site auto-wrap the typechecker recorded on
        `value_expr`, around the already-materialized (and move/copy-resolved)
        `value`. Returns `value` unchanged when there is none.

        Two marks, applied inner first, because a `Result<T?, E>` fed a bare
        `T` carries both (`_arg_result_wrap_ok`): the Optional wrap makes the
        Ok payload, then the Result wrap makes the Result. The name says
        "optional" but this is the one place every caller asks "does this
        transfer owe a wrapper"."""
        opt_type = (getattr(value_expr, 'autowrap_to_optional', None)
                    if apply_optional_wrap else None)
        if opt_type is not None:
            opt_llvm = self._get_llvm_type(opt_type)
            opt_val = ir.Constant(opt_llvm, ir.Undefined)
            opt_val = self.builder.insert_value(
                opt_val, ir.Constant(ir.IntType(1), 1), 0, name="autowrap_some")
            value = self.builder.insert_value(opt_val, value, 1,
                                              name="autowrap_val")
        res_type = getattr(value_expr, 'autowrap_to_result', None)
        if res_type is None:
            return value
        # The same wrap at the other payload kind. The two builders are the
        # ones `ResultOkWrap` / `ResultErrWrap` use at the return position, so
        # an argument-edge Result is laid out by the same code that lays out a
        # returned one.
        if getattr(value_expr, 'autowrap_result_err', False):
            return self._create_result_err_for_return(value, res_type)
        return self._create_result_ok_for_return(value, res_type)

    def _transfer_needs_copy(self, value_expr) -> bool:
        """Whether transferring `value_expr` into a new owner must copy/retain.

        The checker's answer comes first and is authoritative. `_stamp_retain`
        is the sole writer of the `needs_copy` decision (design 270); a
        lowering that rebuilds a node only carries the stamp across, and the
        preservation audit proves the stamp survives every lowering, so when
        it is there nothing below is consulted. The arms below answer only
        where the checker records no decision:

          * `place_value_read` and `frame_owning_read`: the place read and the
            coroutine frame read, two funnels that record no decision of their
            own (for the frame read the transform is the authority).
          * the isinstance tail: a monomorphized generic body. The checker
            files `deferred` there and discharges the tier requirement at the
            call sites (design 219), so no `needs_copy` is stamped on the
            instance body's nodes; the tail re-derives the answer against the
            concrete type. Disabling it miscompiles silently
            (`V32_copy_bound_is_tier_derived` pins it).
        """
        if getattr(value_expr, 'needs_copy', False):
            return True
        # A place value read. Reading a place out as a value is reading a
        # container slot the container still owns: the same duplication
        # `v[i]` and `obj.field` are, and it gets the same rule. The lowering
        # turns the read into a window closure returning its parameter, so the
        # read arrives here as a bare Identifier and the container-slot arm
        # below would never fire for it (design 146).
        #
        # When the element type mentions a type parameter its tier is not
        # knowable from the written type, only from the bounds, and the use
        # site already proved from them that every instantiation can be
        # copied. Which copy is a question for the instantiation, which is
        # where the matching drop is emitted: `_generate_copy` substitutes the
        # monomorphization context and emits the concrete type's own copy.
        if getattr(value_expr, 'place_value_read', False):
            if getattr(value_expr, 'place_abstract_read', False):
                return True
            return self._slot_read_needs_copy(self._expr_type(value_expr))
        # A coroutine frame holds an across-suspend local in a `T?`-encoded
        # field and reads it as `self.name!`. The ForceUnwrap hides the
        # underlying field access from every check below (and from the
        # typechecker's transfer checkpoint). The frame keeps ownership of its
        # field, so this read is a duplication, exactly like `v[i]` /
        # `obj.field` below; the `move` spelling of the same read is not marked
        # (it transfers the frame's own reference via `__saw_forget` instead)
        # (design 124).
        if getattr(value_expr, 'frame_owning_read', False):
            return self._frame_read_needs_copy(value_expr)
        # The generic-instance arm (see the docstring). A body checked at an
        # abstract tier carries no `needs_copy`, so this re-derives the answer
        # against the instance's concrete type, which `type_param_context`
        # supplies below. A non-generic transfer that owes a retain was already
        # answered by the `needs_copy` arm above.
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
            # Reading an owning aggregate (a struct/enum/optional/tuple with
            # cleanup-needing fields) out of a container slot it stays in (an
            # indexed element `v[i]`, a struct field `obj.field`, a tuple
            # element `t.0`) duplicates it while the source keeps ownership.
            # Moving out of such a projection is forbidden, so the read is
            # always a duplication: its owning fields must be retained
            # (copy-with-retain in `_generate_copy`) so the copy's later drop
            # is balanced. A whole-binding read (a bare `Identifier`) is not
            # here: it may be a move, and a Copy one is already caught above
            # (design 65).
            if (isinstance(value_expr, (ArrayIndex, MemberAccess, TupleIndex))
                    and self._needs_cleanup(t)
                    and t.kind in (TypeKind.STRUCT, TypeKind.ENUM,
                                   TypeKind.OPTIONAL, TypeKind.TUPLE)):
                return True
            # An escaping closure read out of a container slot (`buf[i]` inside
            # `Vector<() -> Int>.get`, a closure struct field) is Copy: its env
            # must be retained so the read-out copy's later drop is balanced,
            # or the shared env is freed twice. A bare Identifier closure (a
            # whole-binding move or a borrow-lend) is not here; those keep
            # their move/lend handling.
            if (isinstance(value_expr, (ArrayIndex, MemberAccess, TupleIndex))
                    and t.kind == TypeKind.FUNCTION
                    and getattr(t, 'func_is_escaping', False)):
                return True
            return False
        return False

    def _slot_read_needs_copy(self, t: SawType) -> bool:
        """The container-slot rule, as a question about a type.

        Reading a value out of storage its container keeps is a duplication;
        the rules below are the `v[i]` / `obj.field` arms above, lifted so a
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
                and bool(t.func_is_escaping))

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
        unwrapped payload type: retain a Copy value (`copy()` == a
        refcount bump), an owning aggregate, or an escaping closure env. A NoCopy
        payload is never duplicated — it can only leave the frame through an
        explicit `move`, which takes the `__saw_forget` path instead.

        An un-annotated node is left alone: some synthesized frame reads never
        pass the typechecker, and without a resolved type there is nothing to
        copy against; the rest of the pipeline expects an alias there."""
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
        # TUPLE belongs on this list for the same reason the others do: an
        # owning tuple read out of a frame slot that took a non-retaining alias
        # would have its `Arc` released twice. There is no
        # `_get_cleanup_behavior` answer for a tuple to catch it earlier (a
        # structural type has no name to look a conformance up under), so this
        # kind list is the whole decision.
        return (self._needs_cleanup(t)
                and t.kind in (TypeKind.STRUCT, TypeKind.ENUM,
                               TypeKind.OPTIONAL, TypeKind.TUPLE))

    def _needs_copy_for_struct_init(self, value_expr, field_type: SawType) -> bool:
        """Whether a memberwise struct literal's field initializer must
        copy/retain the value it reads.

        Two questions, and only the first is this site's own. The destination
        question (does a field of this type owe a retain at all) is the tier
        gate below, and it is what distinguishes this boundary from every other
        transfer site. The source question (does this expression read storage
        somebody else keeps owning) is the shared oracle's
        (`_transfer_site_needs_copy` -> `_transfer_needs_copy`), which reads the
        checker's stamped `needs_copy` first and re-derives only what codegen
        owns. Through it, a `move` source copies nothing and a frame-field read
        (`self.name!`) retains like a `MemberAccess` source does.
        """
        # A field type is copy-on-init when it implements Copy, or when it is
        # an aggregate with no whole-type copy() that still owns
        # cleanup-needing payloads (an `Optional<String>`, an owning-payload
        # tuple/struct/enum): initializing such a field from an existing binding
        # is a duplication, and without the recursive retain the stored copy
        # aliases the binding's buffers, which the binding's scope-exit release
        # then frees under the aggregate.
        # `_generate_copy` dispatches these to `_deep_copy_value`. NoCopy and
        # ExplicitCopy sources never reach here as bare identifiers (the
        # typechecker forces `move`/`.copy()` first).
        behavior = self._get_cleanup_behavior(field_type)
        if behavior != "implicit_copy" and not (
                behavior != "no_copy" and self._needs_cleanup(field_type)):
            return False

        # The source question is the shared oracle's. A local node-type list
        # would disagree with the checker on projections (`t.0`, `arr[i]`,
        # `self`), each of which reads storage its owner keeps and owes a
        # retain.
        return self._transfer_site_needs_copy(value_expr)

    def _register_cleanup(self, var_name: str, saw_type: SawType):
        """Register a movable binding (let, param, if-let/guard binding) for
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
        # Capture the binding's storage + drop flag now (design 100). A later
        # inner binding may shadow this name in `self.variables`/`self.drop_flags`;
        # resolving by name at scope-exit would then clean up the wrong (inner,
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
            self._emit_consumes_aware_drop(var_ptr, saw_type)
            if not self.builder.block.is_terminated:
                self.builder.branch(cont_bb)
            self.builder.position_at_start(cont_bb)
            return
        # No drop flag: fall back to the static moved-variable skip.
        if var_name in self.moved_variables:
            return
        self._emit_consumes_aware_drop(var_ptr, saw_type)

    def _emit_consumes_aware_drop(self, var_ptr, saw_type: SawType):
        """The end-of-body release of a `consumes` receiver (design 260).

        The consuming body occupies the prefix slot a hand-written `deinit`
        body would have taken, so two things differ from `_emit_drop_at`:
        1. The type's own `deinit` is not called: the consuming body already
           did whatever teardown its author intended (possibly none, which is
           what makes `File.into_fd()`-style extraction writable). The
           replacement is per endpoint, not per type; every other drop of the
           type is untouched.
        2. The field sweep skips the fields the body moved out; their new owner
           releases them. Reverse declaration order holds among the rest. This
           is decided statically: the every-path-or-no-path rule is what buys
           the flag-free lowering.

        Keyed on the receiver's own pointer, so a non-consuming binding falls
        through to `_emit_drop_at`.
        """
        entry = getattr(self, '_consumes_release_self', None)
        if entry is None or var_ptr is not entry[0]:
            self._emit_drop_at(var_ptr, saw_type)
            return
        saw_type = self._retag_enum(saw_type)
        if saw_type.kind == TypeKind.ENUM:
            # An enum receiver has no fields to move out of, so the synthesized
            # sweep is exactly the active variant's payload release.
            self._emit_enum_cleanup_at(var_ptr, saw_type)
            return
        if saw_type.kind == TypeKind.STRUCT:
            self._emit_field_cleanup_at(var_ptr, saw_type, skip_fields=entry[1])
            return
        self._emit_drop_at(var_ptr, saw_type)

    def _drop_redefined_same_scope(self, var_name: str):
        """Drop the binding a derived same-scope redefinition replaces.

        `var d = read(); let d = parse(move d)` / `let d = d.copy()` replaces
        the old binding. If the old binding still owns a value here (a
        `.copy()`-style derivation), drop it at this point; a `move`-style
        derivation already cleared its drop flag, so the guarded drop is a
        no-op. Its scope-exit entry is retired either way, so the old storage
        is never dropped twice.

        An entry for `var_name` in the innermost cleanup scope means a prior
        owning binding in the same lexical scope (an enclosing-scope shadow
        lives in an outer frame and keeps living). Called after the
        initializer is generated (so `move` has settled the flag) and before
        the replacing binding is registered (design 107)."""
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

    def _cleanup_to_depth(self, cleanup_depth: int):
        """Release every scope a nonlocal exit leaves, innermost first, down to
        (and not including) `cleanup_depth`.

        The funnel for "this edge leaves some scopes; drop what they own".
        Entry points:
          `_cleanup_all_scopes` -- depth 0: a `return`, and the `try` propagation edge that is a return
          `_generate_break_statement` (loops.py) -- bounded at the loop's entry depth
          `_generate_continue_statement` (loops.py) -- bounded at the loop's entry depth
          `_generate_try_propagate` (results.py) -- the catch edge, bounded at the try block's entry depth

        A loop's depth is recorded on `loop_stack` before the loop's own
        bindings register, so a `for`'s owning loop variable is inside the
        unwind. The try block's depth is recorded in `_catch_context`; the
        catch block is a sibling scope, so everything the try body opened is
        left by that branch.

        Nothing is popped: the fall-through edge out of the same body still
        owes its own cleanup, and a drop is guarded by the binding's runtime
        drop flag, so the two edges are independent CFG paths dropping at most
        once each.
        """
        for scope_vars in reversed(self.cleanup_stack[cleanup_depth:]):
            self._cleanup_scope(scope_vars)

    def _cleanup_all_scopes(self):
        """Generate cleanup code for all scopes (for early return).

        Called before return statements to ensure all in-scope variables
        are properly cleaned up. The whole-function case of
        `_cleanup_to_depth`, which is where the walk lives.
        """
        self._cleanup_to_depth(0)

"""THE MONOMORPHIZATION IDENTITY FUNNEL (design 218 unit 1.5).

What IS one instance? The question has exactly one answer, and this module is
where it lives. Three rules decide it, each earned by a miscompile:

  * design 37 — omitted trailing type arguments are filled from the
    declaration's defaults, so `Vector<Int>` and `Vector<Int, Global>` are ONE
    instantiation with one layout and one set of methods;
  * design 61 (L14) — a named type the parser had to guess at is re-tagged
    ENUM when its name denotes one, so drop glue selects the tag switch rather
    than struct field cleanup, and design 51's erased `Box<any Trait>` is
    normalized DOWN to codegen's native arity-1 form so a typechecker-stamped
    arity-2 spelling cannot mangle-miss its registration;
  * design 77 (item 3) — a function type bound to a container's type parameter
    is a STORED closure and carries the escaping bit, which the mangling does
    not encode and a type argument reconstructed from a mangled name has lost.

Design 194 unit 2 learned this once already, for `specialization_key`: two
sides that each answer "what is this instance" separately WILL drift, and the
drift is a silent wrong-layout selection rather than a crash. Design 218 unit
1.5 creates a second asker — the monomorphization phase decides the instance
set, codegen only looks instances up — so the answer moves here and both sides
call it. Codegen's `_fill_default_type_args` / `_canonicalize_type_kind` /
`_mark_stored_closure_escaping` survive as one-line delegators, because they
have many callers and the method spelling reads better at each of them.

The DECLARATION half is the only thing that differs between the two callers —
codegen has its `generic_structs`/`generic_enums`/`enum_types` tables, the
monomorphizer builds its own from the merged AST — so it is abstracted behind
`IdentityEnv` and nothing else is.
"""

import weakref

from ast_nodes import SawType, TypeKind


def is_erased_box(saw_type) -> bool:
    """True for `Box<any Trait, A>` — an owned erased value (a fat pointer).

    The predicate twin of `ExistentialsMixin._is_erased_box`, as a free
    function so the funnel does not need a code generator to ask it.
    """
    return (saw_type is not None and saw_type.kind == TypeKind.STRUCT
            and saw_type.struct_name == "Box" and bool(saw_type.type_args)
            and saw_type.type_args[0].kind == TypeKind.EXISTENTIAL)


class IdentityEnv:
    """What the funnel has to ask about DECLARATIONS, and nothing more.

    Two implementations: `CodegenIdentityEnv` below (reads the code
    generator's own template tables and its live monomorphization context) and
    `monomorphize.MonoIdentityEnv` (reads the tables the phase builds from the
    merged AST). Keeping the surface this small is what makes "the two sides
    cannot disagree about what an instance IS" checkable by reading.
    """

    def type_params(self, base_name):
        """The declared type parameters of a generic struct/enum, or None."""
        raise NotImplementedError

    def is_enum(self, name) -> bool:
        """Whether this name denotes an enum (generic or concrete)."""
        raise NotImplementedError

    def substitute(self, saw_type):
        """Apply the CALLER's active type-parameter binding to a type.

        Only reached for a declared DEFAULT being filled in, which may name an
        earlier parameter (`struct Map<K, V, A = GlobalAllocator>` does not,
        but `struct Pair<A, B = A>` does).
        """
        return saw_type


class CodegenIdentityEnv(IdentityEnv):
    """The code generator's view. Reads its tables LIVE — `type_param_context`
    changes with every body it enters, and the default-filling substitution has
    to see the one in force at the call."""

    def __init__(self, codegen):
        # A WEAK reference on purpose. The code generator caches this env, so a
        # strong one closes a cycle through an object that owns an `ir.Module`
        # — and the test runner's persistent workers compile hundreds of
        # programs in ONE process, where a cycle-collected generator is freed
        # late enough to matter.
        self._cg = weakref.proxy(codegen)

    def type_params(self, base_name):
        cg = self._cg
        decl = cg.generic_structs.get(base_name) or cg.generic_enums.get(base_name)
        return getattr(decl, 'type_params', None) if decl is not None else None

    def is_enum(self, name) -> bool:
        cg = self._cg
        return name in cg.generic_enums or name in cg.enum_types

    def substitute(self, saw_type):
        cg = self._cg
        return cg._substitute_saw_type(saw_type, cg.type_param_context)


def fill_default_type_args(env: IdentityEnv, base_name: str, type_args):
    """Design 37 — append declared defaults for omitted trailing type args.

    THE chokepoint for the identity rule: every mangling and every
    monomorphization of a named type funnels through a caller of this, so
    `Vector<Int>` and `Vector<Int, Global>` produce ONE mangled name and ONE
    monomorphized struct. Idempotent — an already-full argument list passes
    through unchanged, and so does one whose next parameter has no default.
    """
    params = env.type_params(base_name)
    if not params or len(type_args) >= len(params):
        return type_args
    filled = list(type_args)
    for i in range(len(type_args), len(params)):
        default = getattr(params[i], 'default', None)
        if default is None:
            break
        filled.append(env.substitute(default))
    return filled


def canonicalize_type_kind(env: IdentityEnv, saw_type):
    """Re-tag a type whose *kind* was left STRUCT but whose name denotes an
    ENUM (design 61, L14), and normalize an erased box to arity 1 (design 51).

    A named type written in source (`Slot`, `MapSlot<K, V>`) parses as a
    STRUCT-kinded `SawType` because the parser cannot know it is an enum. The
    typechecker's `_resolve_type` rewrites such annotations to ENUM but does
    NOT recurse through POINTER/ARRAY inner types, so a concrete type argument
    reaching an instantiation binding can still be STRUCT-kinded. That wrong
    tag flows into the monomorphization context and then into the drop-glue
    kind switch, which selects struct field cleanup instead of the enum tag
    switch — so owning enum payloads (Map/Set slots, any `Vector<enum>`) never
    run their deinit.

    Fixing the tag at the point the binding is RECORDED keeps the enum an enum
    through every downstream site uniformly. Mangling is kind-agnostic for
    named types (`mangle_named` keys on the bare name), so this never splits or
    renames an instance.
    """
    if saw_type is None:
        return saw_type
    kind = saw_type.kind
    # An erased `Box<any Trait>` (design 51) never monomorphizes through
    # box.saw — its layout is a fat pointer and its teardown is vtable-driven
    # (arity-agnostic: `_emit_erased_box_drop` defaults a missing allocator to
    # Global). Codegen's native canonical form is the arity-1 `Box<any Trait>`
    # (the as-written annotation): every container/enum that embeds it is
    # registered and torn down at arity-1, so its element-drop lookups stay
    # stable. The typechecker, however, canonicalizes `Box<any Trait>` to
    # arity-2 `Box<any Trait, Global>` on expression types, so a `match`/`try`
    # mangling a stamped `Result<T, Box<any Error>>` directly would look up the
    # arity-2 name and mangle-miss the arity-1 registration — then the
    # LLVM-type fallback silently selects a same-sized WRONG monomorphization
    # (design 68, DF6(b)/DF9(c)). Normalize every erased box DOWN to arity-1
    # here so the lookups agree with registration. A non-default allocator
    # argument is preserved.
    if is_erased_box(saw_type):
        targs = saw_type.type_args
        if (len(targs) == 2 and targs[1].kind == TypeKind.STRUCT
                and targs[1].struct_name == "GlobalAllocator"
                and not targs[1].type_args):
            return SawType(TypeKind.STRUCT, struct_name=saw_type.struct_name,
                           type_args=[targs[0]], symbol=saw_type.symbol)
        return saw_type
    if kind == TypeKind.STRUCT and saw_type.struct_name:
        name = saw_type.struct_name
        args = ([canonicalize_type_kind(env, a) for a in saw_type.type_args]
                if saw_type.type_args else saw_type.type_args)
        # Fill omitted trailing defaults (design 37) so the canonical identity
        # matches the monomorphized one — an annotation `Map<Int, R>` becomes
        # `Map<Int, R, Global>`, so its deinit lookup resolves.
        if args:
            args = fill_default_type_args(env, name, args)
        if env.is_enum(name):
            return SawType(TypeKind.ENUM, enum_name=name, type_args=args,
                           symbol=saw_type.symbol)
        if args is not saw_type.type_args:
            return SawType(TypeKind.STRUCT, struct_name=name, type_args=args,
                           symbol=saw_type.symbol)
        return saw_type
    if kind == TypeKind.ENUM and saw_type.type_args:
        args = [canonicalize_type_kind(env, a) for a in saw_type.type_args]
        args = fill_default_type_args(env, saw_type.enum_name, args)
        return SawType(TypeKind.ENUM, enum_name=saw_type.enum_name,
                       type_args=args, symbol=saw_type.symbol)
    if kind == TypeKind.OPTIONAL and saw_type.inner_type:
        return SawType(TypeKind.OPTIONAL,
                       inner_type=canonicalize_type_kind(env, saw_type.inner_type))
    if kind == TypeKind.POINTER and saw_type.inner_type:
        return SawType(TypeKind.POINTER,
                       inner_type=canonicalize_type_kind(env, saw_type.inner_type),
                       pointer_mutable=saw_type.pointer_mutable)
    if kind == TypeKind.REFERENCE and saw_type.inner_type:
        return SawType(TypeKind.REFERENCE,
                       inner_type=canonicalize_type_kind(env, saw_type.inner_type),
                       reference_mutable=saw_type.reference_mutable)
    if kind == TypeKind.TUPLE and saw_type.element_types:
        return SawType(TypeKind.TUPLE,
                       element_types=[canonicalize_type_kind(env, e)
                                      for e in saw_type.element_types])
    if kind == TypeKind.ARRAY and saw_type.array_element_type:
        return SawType(TypeKind.ARRAY,
                       array_element_type=canonicalize_type_kind(
                           env, saw_type.array_element_type),
                       array_size=saw_type.array_size)
    return saw_type


def mark_stored_closure_escaping(saw_type):
    """Mark a function TYPE bound to a container's type parameter as escaping
    (design 77 item 3).

    A closure stored in a container (a Vector/Map/Set element, an
    Optional/tuple/array payload of one) is an OWNING value: its refcounted env
    must be retained on copy and released at teardown. The typechecker stamps
    the escaping bit on such stored positions, but it is not part of the
    mangling, so a type argument reconstructed from a mangled key arrives with
    the bit cleared — and then `_needs_cleanup`/the Copy-bound predicate treat
    the element as non-owning: the env leaks and copies are unbalanced.

    A function type in a genuine parameter role never reaches here (it lives in
    a method signature, not a container type argument). Returns a fresh
    `SawType` so no shared instance is mutated.
    """
    if saw_type is None:
        return saw_type
    k = saw_type.kind
    if k == TypeKind.FUNCTION and not saw_type.func_is_escaping:
        return SawType(TypeKind.FUNCTION, param_types=saw_type.param_types,
                       func_return_type=saw_type.func_return_type,
                       func_is_sync=saw_type.func_is_sync,
                       func_is_unsafe=saw_type.func_is_unsafe,
                       func_is_escaping=True)
    if k == TypeKind.OPTIONAL and saw_type.inner_type is not None:
        return SawType(TypeKind.OPTIONAL,
                       inner_type=mark_stored_closure_escaping(saw_type.inner_type))
    if k == TypeKind.ARRAY and saw_type.array_element_type is not None:
        return SawType(TypeKind.ARRAY,
                       array_element_type=mark_stored_closure_escaping(
                           saw_type.array_element_type),
                       array_size=saw_type.array_size)
    if k == TypeKind.TUPLE and saw_type.element_types:
        return SawType(TypeKind.TUPLE,
                       element_types=[mark_stored_closure_escaping(e)
                                      for e in saw_type.element_types])
    return saw_type


def canonical_struct_args(env: IdentityEnv, base_name: str, type_args):
    """The three rules in the order `_ensure_monomorphized_struct` applies them:
    fill defaults, re-tag kinds, restore the stored-closure escaping bit.

    This IS the struct/enum instance identity — feed the result to
    `mangle_named` and the key is the mangled symbol, which is why the manglers
    need no monomorphization knowledge of their own.
    """
    args = fill_default_type_args(env, base_name, type_args)
    args = [canonicalize_type_kind(env, a) for a in args]
    return [mark_stored_closure_escaping(a) for a in args]


def canonical_enum_args(env: IdentityEnv, base_name: str, type_args):
    """The enum twin. `_ensure_monomorphized_enum` deliberately does NOT mark
    stored closures — an enum payload is not a container element, and adding
    the bit here would split an identity the struct side does not.
    """
    args = fill_default_type_args(env, base_name, type_args)
    return [canonicalize_type_kind(env, a) for a in args]

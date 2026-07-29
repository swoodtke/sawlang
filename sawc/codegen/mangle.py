"""
Canonical name mangling for the Saw code generator.

This is the single source of truth for turning Saw types and generic
instantiations into unique LLVM-identifier strings. Every producer that
REGISTERS a specialized struct/enum/function and every consumer that LOOKS one
up must go through these functions, so that a name computed independently in two
places is always identical.

Design goals
------------
- Total: `mangle_type` handles every `TypeKind`.
- Injective: two structurally different types never produce the same string.
  Ambiguities like `Box<Box<Int>>` vs `Box<Box, Int>` (arity) and
  `Result<(Int,Int),E>` vs `Result<(String,Bool),E>` (tuple payloads) are the
  exact bug class this module exists to kill.
- Deterministic and order-preserving over type arguments / tuple elements.
- Emits only characters valid in LLVM identifiers.

Grammar sketch (`$` is the one delimiter; the lexer forbids `$` inside any Saw
identifier, so it can never appear inside a user type name):

    primitive      := Int | UInt | Int8 .. Int64 | UInt8 .. UInt64
                    | Float | Bool | String | Void
    named<args>    := Name '$' <arity> '$' type ('$' type)*      # struct / enum with type args
    named          := Name                                        # struct / enum, no type args
    tuple          := '$Tup$' <arity> ('$' type)*
    optional       := '$Opt$' type
    array          := '$Arr$' <size> '$' type
    pointer        := ('$PtrM$' | '$PtrC$') type
    reference      := ('$RefM$' | '$RefC$') type
    existential    := '$Any$' TraitName                       # `any Trait` (design 51)
    function       := '$Fn$' <arity> ('$' type)* '$To$' type
    type_param     := '$P$' Name            # should be substituted before mangling
    self           := '$Self'               # should be resolved before mangling

Composite types are tagged with a leading `$`; named types never start with `$`
(identifiers can't), and after a named type's `$` the arity is a digit, whereas
every argument starts with a letter or `$`. That keeps the encoding uniquely
decodable, hence injective. A struct named e.g. "Tup" is safely distinct from a
tuple because the tuple tag carries the leading `$` a name cannot.

Type aliases: `mangle_type` mangles the alias by whatever `SawType` it is handed.
Callers that want alias transparency resolve aliases (`_resolve_type_alias`)
before mangling; this module does not resolve them itself.
"""

from ast_nodes import SawType, TypeKind


_PRIMITIVES = {
    TypeKind.INT: "Int",
    TypeKind.UINT: "UInt",
    TypeKind.INT8: "Int8",
    TypeKind.INT16: "Int16",
    TypeKind.INT32: "Int32",
    TypeKind.INT64: "Int64",
    TypeKind.UINT8: "UInt8",
    TypeKind.UINT16: "UInt16",
    TypeKind.UINT32: "UInt32",
    TypeKind.UINT64: "UInt64",
    TypeKind.FLOAT: "Float",
    TypeKind.BOOL: "Bool",
    TypeKind.STRING: "String",
    TypeKind.VOID: "Void",
}


def mangle_type(t: SawType) -> str:
    """Return the canonical, collision-free mangling of a Saw type."""
    if t is None:
        return "Void"

    kind = t.kind

    prim = _PRIMITIVES.get(kind)
    if prim is not None:
        return prim

    if kind == TypeKind.STRUCT:
        return mangle_named(t.struct_name, t.type_args)

    if kind == TypeKind.ENUM:
        return mangle_named(t.enum_name, t.type_args)

    if kind == TypeKind.TUPLE:
        elems = t.element_types or []
        body = "".join("$" + mangle_type(e) for e in elems)
        return f"$Tup${len(elems)}{body}"

    if kind == TypeKind.OPTIONAL:
        return "$Opt$" + mangle_type(t.inner_type)

    if kind == TypeKind.ARRAY:
        size = t.array_size if t.array_size is not None else 0
        return f"$Arr${size}$" + mangle_type(t.array_element_type)

    if kind == TypeKind.POINTER:
        tag = "$PtrM$" if t.pointer_mutable else "$PtrC$"
        return tag + mangle_type(t.inner_type)

    if kind == TypeKind.REFERENCE:
        tag = "$RefM$" if t.reference_mutable else "$RefC$"
        return tag + mangle_type(t.inner_type)

    if kind == TypeKind.FUNCTION:
        params = t.param_types or []
        body = "".join("$" + mangle_type(p) for p in params)
        return f"$Fn${len(params)}{body}$To$" + mangle_type(t.func_return_type)

    if kind == TypeKind.TYPE_PARAM:
        # An unsubstituted type parameter reaching the mangler is a bug in the
        # caller, but stay total so it surfaces as a clear symbol rather than a
        # crash.
        return "$P$" + (t.type_param_name or "T")

    if kind == TypeKind.EXISTENTIAL:
        # `any Trait` (design 51): the erased type is identified by its trait, so
        # `Box<any Shape>` and `&any Shape` monomorphize/lookup consistently.
        return "$Any$" + (t.existential_trait or "")

    if kind == TypeKind.SELF:
        return "$Self"

    if kind == TypeKind.MODULE:
        return "$Mod$" + (t.module_name or "")

    return "$Unknown$" + kind.name


def mangle_named(base: str, type_args) -> str:
    """Canonical name for a (possibly generic) named type or its monomorphization.

    Used symmetrically by producers (registering a specialized struct/enum, e.g.
    `Result<(Int,Int), MyErr>`) and consumers (looking it up). With no type
    arguments this returns the bare name, so non-generic types keep their plain,
    unmangled symbol.
    """
    if not type_args:
        return base
    body = "$".join(mangle_type(a) for a in type_args)
    return f"{base}${len(type_args)}${body}"


def mangle_function(name: str, type_args) -> str:
    """Canonical symbol for a generic function instantiation (e.g. identity<Int>).

    Non-generic functions never pass through here; their source name is used
    directly so linker/entry behaviour (`main`, extern functions) is untouched.
    """
    return mangle_named(name, type_args)


def mangle_method(struct_name: str, method_name: str, param_names=None,
                  method_type_args=None) -> str:
    """Canonical symbol for a method or init.

    `struct_name` is the already-mangled receiver type (e.g. `Vector$1$Int`), so
    a method symbol composes the struct's specialization with the method name.

    For init methods, the parameter-name signature is appended to allow
    overloading. Init resolution in the typechecker matches on the *set* of
    parameter names and rejects two inits with the same names as ambiguous, so a
    name-based key uniquely identifies the selected init; a same-names/
    different-types collision is unreachable in the current language.

    For a method-level GENERIC method (`func map<U>(...)`, brief 36), the
    explicit method type arguments are appended with the same length-prefixed
    scheme `mangle_named` uses, so the symbol composes (struct args) x (method
    args): `Vector$1$Int.map<String>` -> `Vector$1$Int_map$1$String`. The `_`
    separates the struct-mangle from the method, and the trailing `$n$...` is the
    canonical type-arg encoding — jointly injective.
    """
    if param_names is not None:
        base = f"{struct_name}_{method_name}_{'_'.join(param_names)}"
    else:
        base = f"{struct_name}_{method_name}"
    if method_type_args:
        return mangle_named(base, method_type_args)
    return base

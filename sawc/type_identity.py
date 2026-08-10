"""Module-qualified type identity (design 144).

A type's identity is `(defining module, name)`, not a bare name. Two modules
that each declare a private `struct Header` declare two DIFFERENT types, with
two layouts, two `Vector<Header>` instantiations and two method symbol
families. Before this, a type's identity was the bare name threaded through
`SawType.struct_name`, `Codegen.struct_types`, monomorphization keys, method
mangling and the derivation-key sets, so the two collided and the compiler had
to refuse the program ("ambiguous struct `Header`", DF-142a) rather than
silently register one layout and miscompile the other module against it.

REPRESENTATION (the one chosen; design 144 asked for exactly one)
-----------------------------------------------------------------
The identity is a single FUSED STRING carried in the existing name slots —
`SawType.struct_name` / `enum_name` / `existential_trait`, `StructSymbol`'s
namespace key, the AST declaration's stamped `type_identity`:

    Header                      # root / entry module, and std
    Header$m$dep                # module `dep`
    Header$m$pkg_sub            # module `pkg.sub`

Fusing rather than adding a sibling `def_module` field to `SawType` is
deliberate. Codegen re-synthesizes a `SawType` from a bare name in dozens of
places (derived-copy bodies, cleanup keys, receiver canonicalization); a
sibling field is silently DROPPED at every one of them, and a dropped identity
is a wrong layout. A name is copied by every one of those sites for free. The
cost is display — which is one function, applied where names are rendered, and
whose failure mode is an ugly message rather than a miscompile.

`$m$` is design 142's delimiter for module-qualified private symbols
(`registration._module_private_symbol`), reused here so the two schemes compose
instead of inventing a second convention. The lexer forbids `$` inside a Saw
identifier, so a qualified identity can never collide with a name an author
could write, and `display_name` is a total, exact inverse.

WHICH MODULES QUALIFY
---------------------
`qualifies()` below: every non-root module, plus — since design 204 — the
FILE-PRIVATE types of a std file. Three consequences worth stating:

* The root module is `()` — the entry file, and the whole single-file
  compilation path. Nothing there is qualified, so every single-file program in
  the corpus emits byte-identical IR (the design-126 irdet property).
* std's PUBLIC types are exempt. std is one shared prelude compiled into every
  program, and its published type names are compiler-known in hundreds of
  places (`Vector`, `String`, `Result`, `Box`). Qualifying them would rename
  every symbol in every program to no purpose, and design 204 explicitly keeps
  the public surface's exposure exactly as designs 82/150/194 left it.
* std's PRIVATE types are NOT exempt (design 204). Design 82 makes each std
  FILE its own module, so a type that file keeps to itself is that file's:
  `State` in `std/once.saw` is `State$m$std_once`, it reserves nothing in a
  user program, and a second std file may own the name too. This is DF-140h's
  module-local identity — landed for a private std `static`, never for a type
  — finally applied to type declarations.

`builtin.saw` is exempt WHOLESALE: it declares the compiler's own vocabulary
(the copy family, `Ordering`, `Atomic`, `Range`, `__Poll`), every name of which
the compiler either publishes or reaches by string. It holds no private type,
so there is nothing there for the rule to free.
"""

from typing import Optional, Tuple

# The std file whose declarations are the compiler's own vocabulary. Nothing in
# it is file-private, and every name in it is either published or reached by
# string from `sawc/`, so it never qualifies (design 204).
STD_VOCABULARY_LEAF = "builtin"

# Design 142's delimiter (`registration._module_private_symbol`). One scheme,
# two users: a private function's codegen symbol and a type's identity.
QUALIFIER = "$m$"


def module_tag(module: Tuple[str, ...]) -> str:
    """A defining module rendered for an LLVM symbol name: identifier-safe,
    stable, and distinct per module (`("<std>", "data")` -> `std_data`)."""
    parts = [p for p in module if p != "<std>"]
    if module[:1] == ("<std>",):
        parts = ["std"] + parts
    raw = "_".join(parts) if parts else "root"
    return "".join(c if (c.isalnum() or c == "_") else "_" for c in raw)


def is_std_module(module: Optional[Tuple[str, ...]]) -> bool:
    """Whether `module` is a std FILE's module (`("<std>", "once")`)."""
    return bool(module) and module[:1] == ("<std>",)


def qualifies(module: Optional[Tuple[str, ...]], private: bool = False) -> bool:
    """Whether a type defined in `module` carries a module-qualified identity.

    `private` is the declaration's own visibility, and it only matters inside
    std: a user module's types qualify either way (design 144), while a std
    file qualifies exactly what it keeps to itself (design 204). See the module
    docstring for why root and std's published surface are exempt."""
    if not module:
        return False
    if is_std_module(module):
        if not private:
            return False
        return module[1:2] != (STD_VOCABULARY_LEAF,)
    return True


def type_identity(name: str, module: Optional[Tuple[str, ...]],
                  private: bool = False) -> str:
    """The identity of type `name` defined in `module`.

    Idempotent: an already-qualified name is returned unchanged. Registration
    runs again on the same AST whenever the front half re-enters (the place
    lowering and the coroutine transform both do), and re-qualifying would
    produce `Header$m$dep$m$dep`. Same shape as DF-146a's `_derivation_slot`.
    """
    if not name or QUALIFIER in name:
        return name
    if not qualifies(module, private):
        return name
    return f"{name}{QUALIFIER}{module_tag(module)}"


def declaration_base(name: Optional[str]) -> Optional[str]:
    """The DECLARATION this (possibly monomorphized) type name instantiates,
    with its module qualifier INTACT.

    `Vector$1$Int` -> `Vector`; `State$m$std_once` -> `State$m$std_once`;
    `Box$m$dep$1$Int` -> `Box$m$dep`. The naive `name.split('$')[0]` predates
    design 144 and reads a qualifier as an instantiation suffix, which silently
    answers a question about `State$m$std_once` with whatever a bare `State`
    says — a wrong-type answer, not a missing one. That was invisible while
    only user modules qualified (design 144 landed no in-tree case); design 204
    qualifies std's own internals, and the first symptom was `Data` losing its
    `Send`ness because its `DataBuf` field's assertion was filed under the
    identity and looked up under the bare name.

    `codegen.mangle`'s grammar is what makes this decidable: a monomorphized
    name is `Base$<arity>$<args>` and `$m$<tag>` is part of the Name itself.
    """
    if not name or QUALIFIER not in name and '$' not in name:
        return name
    parts = name.split('$')
    out = [parts[0]]
    i = 1
    while i + 1 < len(parts) and parts[i] == 'm':
        out.extend(('m', parts[i + 1]))
        i += 2
    return '$'.join(out)


def is_module_local(identity: Optional[str],
                    module: Optional[Tuple[str, ...]]) -> bool:
    """Whether a type's NAME is nameable only from inside `module` itself.

    True for exactly the std file-private types design 204 introduced. A user
    module's qualified types stay nameable from an importer (that is what
    design 144's public same-name coexistence rests on), so they are not
    module-local and keep their binding in the shared name view."""
    return is_std_module(module) and is_qualified(identity)


def display_name(identity: Optional[str]) -> Optional[str]:
    """The SHORT name a diagnostic, a doc page or an AST dump shows.

    Total and exact: `$` cannot occur in a source identifier, so the split
    point is unambiguous and a plain name passes through untouched."""
    if not identity:
        return identity
    idx = identity.find(QUALIFIER)
    return identity if idx < 0 else identity[:idx]


def identity_tag(identity: Optional[str]) -> Optional[str]:
    """The module tag carried by an identity, or None when it carries none."""
    if not identity:
        return None
    idx = identity.find(QUALIFIER)
    return None if idx < 0 else identity[idx + len(QUALIFIER):]


def is_qualified(identity: Optional[str]) -> bool:
    return bool(identity) and QUALIFIER in identity


def decl_identity(decl) -> str:
    """The identity of a type DECLARATION node (`Struct` / `Enum` / `Trait` /
    `TypeDefinition`).

    Declaration name slots keep the name the AUTHOR wrote — that is what
    diagnostics, `--emit-docs` and the AST dump render, and what
    `make_accessible` binds — and carry the identity alongside in
    `type_identity`. REFERENCE slots (`SawType.struct_name`,
    `Extension.struct_name`, `StructInit.struct_name`) are the opposite: they
    hold the identity, because everything downstream of them is keyed by it.

    The fallback covers declarations the typechecker never registered:
    compiler-synthesized nodes and the codegen-side builtins, none of which
    belongs to a qualifying module."""
    return getattr(decl, 'type_identity', "") or decl.name

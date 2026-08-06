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
`qualifies()` below: every non-root module EXCEPT std. Two consequences worth
stating:

* The root module is `()` — the entry file, and the whole single-file
  compilation path. Nothing there is qualified, so every single-file program in
  the corpus emits byte-identical IR (the design-126 irdet property).
* std is exempt. std is one shared prelude compiled into every program, and its
  type names are compiler-known in hundreds of places (`Vector`, `String`,
  `Result`, `Box`). Qualifying them would rename every symbol in every program
  to no purpose: a name clash INSIDE std is a std bug we want reported, not
  silently split into two types. Design 82 already gives each std file its own
  module identity for VISIBILITY; that is a separate axis and stays.
"""

from typing import Optional, Tuple

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


def qualifies(module: Optional[Tuple[str, ...]]) -> bool:
    """Whether types defined in `module` carry a module-qualified identity.

    See the module docstring for why root and std are exempt."""
    if not module:
        return False
    if module[:1] == ("<std>",):
        return False
    return True


def type_identity(name: str, module: Optional[Tuple[str, ...]]) -> str:
    """The identity of type `name` defined in `module`.

    Idempotent: an already-qualified name is returned unchanged. Registration
    runs again on the same AST whenever the front half re-enters (the place
    lowering and the coroutine transform both do), and re-qualifying would
    produce `Header$m$dep$m$dep`. Same shape as DF-146a's `_derivation_slot`.
    """
    if not name or QUALIFIER in name:
        return name
    if not qualifies(module):
        return name
    return f"{name}{QUALIFIER}{module_tag(module)}"


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

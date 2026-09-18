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
    Header$m$pkg_0sub           # module `pkg_sub` — a DIFFERENT module, and
                                # `module_tag` keeps the two apart

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
(the copy family, `Ordering`, `Atomic`, `Range`), every name of which
the compiler either publishes or reaches by string. It holds no private type,
so there is nothing there for the rule to free.
"""

import os
from typing import Optional, Tuple

# The std file whose declarations are the compiler's own vocabulary. Nothing in
# it is file-private, and every name in it is either published or reached by
# string from `sawc/`, so it never qualifies (design 204).
STD_VOCABULARY_LEAF = "builtin"

# The directory std's sources live in. `builtin.saw` sits one level above it.
STD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "std")


def std_leaf(source_file: Optional[str]) -> Optional[str]:
    """THE std source-file -> module-leaf funnel (design 218 unit 1).

    A std file's leaf is its path RELATIVE TO `std/`, extension dropped, path
    separators rendered as dots — which is exactly the tail of the `import`
    that reaches it:

        sawc/std/vector.saw          -> `vector`          (`import std.vector`)
        sawc/std/compiler/frame.saw  -> `compiler.frame`  (`import std.compiler.frame`)
        sawc/builtin.saw             -> `builtin`

    Returns None for a file that is not a std source, so a caller can tell
    "user code" from "std file whose leaf is X".

    Design 82 makes each std FILE its own module `("<std>", leaf)`; before
    design 218 every std file sat directly in `std/` and the leaf was just the
    basename, computed independently at each of the entry points below. A
    SUBDIRECTORY makes basename and import spelling disagree, so the four
    answers have to come from one place or `std/compiler/frame.saw` is module
    `frame` to one of them and `compiler.frame` to another.

    ENTRY POINTS — every place a std source path becomes a module name:
      * `sawc.build_builtin_namespace` — the (leaf -> symbols) surface map that
        `import std.<leaf>` re-exposes and the prelude gate keys on.
      * `sawc.compute_std_codegen_exclusions` — which std files a program
        code-generates, and `sawc._filter_std_ast`, which drops the rest.
      * `TypeChecker._vis_module_for_source` (typechecker/core.py) — the
        design-80/204 visibility module of a declaration.
      * `DocsEmitter._leaf_of` / `_std_path` (docs_emit.py) — `--emit-docs`
        module names.
    The import side is `_process_std_import`, which joins the path after `std`
    on the same dot.
    """
    if not source_file:
        return None
    try:
        norm = os.path.abspath(source_file)
    except Exception:
        return None
    base = os.path.basename(norm)
    if not base.endswith(".saw"):
        return None
    prefix = STD_DIR + os.sep
    if norm.startswith(prefix):
        rel = norm[len(prefix):-4]
        return rel.replace(os.sep, ".")
    if base == "builtin.saw":
        return STD_VOCABULARY_LEAF
    return None

# Design 142's delimiter (`registration._module_private_symbol`). One scheme,
# two users: a private function's codegen symbol and a type's identity.
QUALIFIER = "$m$"


# The two MARKER DIGITS that follow an escaping `_` inside a rendered module
# tag (see `module_tag`). A digit is the right marker because an escaped path
# component never BEGINS with one, so the character after a separator can never
# be read as a marker and the two roles a `_` can play stay decidable.
_MARK_UNDERSCORE = "0"   # `_0` — a literal `_` inside a component
_MARK_CHARACTER = "1"    # `_1<hex>_` — any other character a component holds

# What the `("<std>", ...)` marker renders as. Reserved: a USER path whose first
# component is this word takes the character escape instead (see `module_tag`),
# so `("<std>", "once")` and `("std", "once")` are two tags.
_STD_HEAD = "std"


def _char_escape(ch: str) -> str:
    return "_%s%x_" % (_MARK_CHARACTER, ord(ch))


def _escape_component(part: str) -> str:
    """One path component, escaped so that `_` can separate components.

    `_` -> `_0`; any character outside `[A-Za-z0-9]` -> `_1<hex codepoint>_`;
    every other character stands for itself. A LEADING `0` or `1` takes the
    character escape too, so an escaped component never begins with a marker
    digit."""
    out = []
    for i, ch in enumerate(part):
        if ch == "_":
            out.append("_" + _MARK_UNDERSCORE)
        elif (ch.isascii() and ch.isalnum()
              and not (i == 0 and ch in (_MARK_UNDERSCORE, _MARK_CHARACTER))):
            out.append(ch)
        else:
            out.append(_char_escape(ch))
    return "".join(out)


def _escaped_components(module: Tuple[str, ...]) -> list:
    """The ESCAPED path components `module_tag` joins, one per path segment.

    A std module is `("<std>", leaf)` where the leaf is the file's path under
    `std/` with separators written as dots (`std_leaf`), so its dots are real
    component boundaries and split into components here: `("<std>",
    "compiler.frame")` is three components, `std` / `compiler` / `frame`,
    exactly as `import std.compiler.frame` spells it.

    A USER path whose first component is `std` renders that component through
    the character escape (`_173_td`) rather than as itself, which is what
    reserves the marker's rendering for the marker. The decode is untouched by
    this — `_173_td` reads back as `std` like any other escape — so the pair
    stays two distinct tags for one unambiguous component tuple each."""
    if module[:1] == ("<std>",):
        parts = [_STD_HEAD]
        for seg in module[1:]:
            parts.extend(seg.split("."))
        return [_escape_component(p) for p in parts]
    out = [_escape_component(p) for p in module]
    if out[:1] == [_STD_HEAD]:
        out[0] = _char_escape(_STD_HEAD[0]) + _escape_component(_STD_HEAD[1:])
    return out


def module_tag(module: Tuple[str, ...]) -> str:
    """A defining module rendered for an LLVM symbol name: identifier-safe,
    stable, and INJECTIVE over the complete path (`("<std>", "data")` ->
    `std_data`).

    THE ENTRY MODULE RENDERS EMPTY. Every non-empty path renders at least one
    character, so the empty string is the one tag no module can take — while the
    word `root`, which this used to return for the entry module, is exactly what
    a user module named `root` renders as (SL-274 review r1 finding P2). Both
    became `helper$m$root` and codegen died with `internal compiler error:
    helper$m$root`.

    THE PATH'S COMPONENTS ARE ESCAPED, because `"_".join(parts)` is not
    injective either: it renders `("a", "b")` and `("a_b",)` alike, so a private
    `helper` in module `a_b` and a public `helper` in `a.b` both became
    `helper$m$a_b` and codegen died the same way (SL-274 review r2 finding).
    `_escape_component` above escapes a literal `_` as `_0` and anything outside
    `[A-Za-z0-9]` as `_1<hex>_`, and the components are joined with a bare `_`:

        ()                          -> ``              the entry module
        ("dep",)                    -> `dep`
        ("a", "b")                  -> `a_b`
        ("a_b",)                    -> `a_0b`
        ("<std>", "once")           -> `std_once`
        ("<std>", "compiler.frame") -> `std_compiler_frame`
        ("std", "once")             -> `_173_td_once`   a USER module `std.once`

    INJECTIVITY: decode left to right. A `_` followed by `0` is a literal
    underscore; a `_` followed by `1` opens a `_1<hex>_` character escape, whose
    hex digits run to the next `_`; any other `_` — including one at the end of
    the string or before another `_` — ENDS a component. The three cases are
    disjoint because the character after a separator is the first character of
    the next escaped component, and an escaped component never begins with `0`
    or `1`. So the decode is total and recovers the exact component tuple, and a
    rendering shared by two paths is impossible. The empty path renders as the
    empty string, which no non-empty path can render, so the entry module keeps
    its own distinct tag; the `<std>` marker renders as `std`, which
    `_escaped_components` denies to a user path, so the std half of the domain
    keeps its own too.

    THE TRADE-OFF, deliberate: the escape is paid by the component that CONTAINS
    an underscore, not by the path that has several components. `("<std>",
    "once")` -> `std_once` and `("dep",)` -> `dep` therefore read exactly as they
    did before this rule — which is what keeps std's tags (`State$m$std_once`,
    `Slot$m$std_compiler_frame`) and the everyday one-component user tag stable
    — while `("modules", "d144_pub_a")` now reads `modules_d144_0pub_0a`. The
    other way round (a longer separator, components verbatim) would have moved
    every std tag instead, and std's are the ones the compiler, its tests and its
    prose name.

    Consequences of the empty rendering, both deliberate: a tag is
    `[A-Za-z0-9_]*` rather than `+`, which `ErrorReporter._QUALIFIER_RE` matches
    so a bare `$m$` is scrubbed out of a diagnostic like any other qualifier;
    and `$` is forbidden in a Saw identifier — and never produced here — so a
    delimiter can never collide with a name an author could write."""
    return "_".join(_escaped_components(module))


def is_std_module(module: Optional[Tuple[str, ...]]) -> bool:
    """Whether `module` is a std FILE's module (`("<std>", "once")`)."""
    return bool(module) and module[:1] == ("<std>",)


# The std types the COMPILER ITSELF emits references to (design 218 unit 1).
#
# A synthesized reference has to reach STD's declaration whatever the user's
# own module declares, and the only thing that distinguishes two same-named
# types downstream is the identity string — codegen keys every table by it. So
# these carry a module-qualified identity even though std's PUBLIC surface is
# otherwise exempt (see the module docstring), and the coroutine transform
# emits that identity rather than the bare name.
#
# They stay NAMEABLE, which is the point of publishing them: the qualified
# identity is bound in the SHARED name view under the plain spelling (see
# `is_module_local`), so `import std.compiler.frame.{Poll}` reaches it and a
# user `enum Poll` simply rebinds the spelling to its OWN identity instead of
# colliding. `Resumable` needs none of this — a trait and a user's struct or
# enum of the same name live in different tables and never meet.
#
# `Slot` and `UnsafeRef` joined them at design 218 stage 1 (DF-218g), which is
# what turned this from a reference rule into a COMPILATION rule. Since a
# driven program's frames are made of slots, `std.compiler.frame` is compiled
# into every one of them whether or not the source imports it — and `Slot` is a
# name user programs really do use. Design 82's exclusion cannot be the answer
# (a type the compiler must always emit cannot be excluded), so the identity
# is: std's `Slot` is `Slot$m$std_compiler_frame` from its declaration all the
# way to its LLVM symbols, and the bare name stays the user's to spend on a
# struct or an enum of their own.
#
# `Thread` and `VoidThread` joined at design 242 unit 1, on both counts at once.
# They are what `Thread.spawn { … }` evaluates to, and that form names no type
# at the source level — the typechecker and spawn codegen mint the reference —
# so the synthesized reference must reach std's declaration whatever the module
# it lands in declares. And they are COMPILED IN whether or not a program
# imports `std.task`: the prelude `std.taskgroup` spawns its own worker pool,
# which drags the leaf in through design 82's transitive closure, so exclusion
# cannot be the answer here either. `Thread` is a name real programs use — SOS's
# public `sos` module has a `struct Thread` for a kernel thread object, which is
# how this was found.
COMPILER_EMITTED_STD_TYPES = {"Poll", "Slot", "UnsafeRef", "Thread", "VoidThread"}


def qualifies(module: Optional[Tuple[str, ...]], private: bool = False,
              name: Optional[str] = None) -> bool:
    """Whether a type defined in `module` carries a module-qualified identity.

    `private` is the declaration's own visibility, and it only matters inside
    std: a user module's types qualify either way (design 144), while a std
    file qualifies exactly what it keeps to itself (design 204). See the module
    docstring for why root and std's published surface are exempt.

    `name` is consulted only for the compiler-emitted carve-out above, which is
    the one case where a PUBLIC std type qualifies."""
    if not module:
        return False
    if is_std_module(module):
        if module[1:2] == (STD_VOCABULARY_LEAF,):
            return False
        if name in COMPILER_EMITTED_STD_TYPES:
            return True
        return private
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
    if not qualifies(module, private, name):
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


# The compiler-known wrappers that OCCUPY EXACTLY THEIR PAYLOAD. A field of one
# costs no wrapper word and its address IS the payload's, which is what makes
# `Atomic<T>`/`SpinLock<T>` byte-identical to the versions with no cell and what
# makes an MMIO register block's offsets land on the real registers.
_LAYOUT_TRANSPARENT = frozenset((
    "UnsafeMutableInterior",     # design 186 — the interior-mutability cell
    "ReadOnly", "WriteOnly",     # design 112 — MMIO access markers
))


def is_layout_transparent(name: Optional[str]) -> bool:
    """Whether a (possibly monomorphized) type NAME occupies exactly its payload.

    ONE DEFINITION, both sides, for the reason `mono_identity` exists: codegen
    lowers such a type to its payload's LLVM type, and the monomorphization
    phase must not splice methods onto an instantiation whose layout no wrapper
    struct describes. `Mutex<Int?>`'s `value: UnsafeMutableInterior<Int?>` field
    is a bare `{i1, i64}`, so a synthesized `UnsafeMutableInterior$1$$Opt$Int_deinit`
    taking a pointer to the WRAPPER is a symbol nothing can call with the field's
    own address — which is what the drop glue tried to do the moment the
    instance registry started registering these instantiations up front.

    Answered on the DECLARATION, so an instantiation and its template agree.
    """
    return declaration_base(name) in _LAYOUT_TRANSPARENT


def is_module_local(identity: Optional[str],
                    module: Optional[Tuple[str, ...]]) -> bool:
    """Whether a type's NAME is nameable only from inside `module` itself.

    True for exactly the std file-private types design 204 introduced. A user
    module's qualified types stay nameable from an importer (that is what
    design 144's public same-name coexistence rests on), so they are not
    module-local and keep their binding in the shared name view. Neither is a
    COMPILER-EMITTED std type: it is qualified for a different reason (so a
    synthesized reference cannot be shadowed) and is public, so it keeps its
    shared binding and stays importable."""
    return (is_std_module(module) and is_qualified(identity)
            and display_name(identity) not in COMPILER_EMITTED_STD_TYPES)


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

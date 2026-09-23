"""
Saw Language Namespace
Unified symbol table for all declarations.
"""

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Any, Tuple, Set, Union
from enum import Enum, auto
from ast_nodes import (SawType, TypeKind, Function, Struct, Enum as SawEnum,
                       Extension, TypeParameter, Visibility,
                       PRIMITIVE_EXT_KINDS)
from type_identity import declaration_base, is_qualified


class SymbolKind(Enum):
    FUNCTION = auto()
    STRUCT = auto()
    ENUM = auto()
    METHOD = auto()
    TRAIT = auto()
    TYPE_ALIAS = auto()
    MODULE = auto()
    STATIC = auto()


# Symbol objects hold only immutable declaration data. Builtin symbols (String,
# Vector, Result, ...) are shared by reference into every module namespace via
# `Namespace.merge_into`, so per-compilation state written onto a symbol would
# alias across all module views. Codegen artifacts live in codegen-owned side
# tables keyed by mangled name (`Codegen.struct_types` / `enum_types` /
# `functions`). Do not add codegen-populated fields here; extend the side
# tables instead.
@dataclass
class FunctionSymbol:
    """Symbol for a function or method."""
    kind: SymbolKind = SymbolKind.FUNCTION
    param_types: List[SawType] = field(default_factory=list)
    param_names: List[str] = field(default_factory=list)
    return_type: Optional[SawType] = None
    type_params: List[TypeParameter] = field(default_factory=list)
    default_values: List[Optional[Any]] = field(default_factory=list)
    is_static: bool = False
    is_init: bool = False
    self_mutable: bool = False
    self_is_reference: bool = True  # True for '&self' or '&var self'
    is_variadic: bool = False
    # Effects:
    #  - is_sync: declared `sync` (body checked suspension-free)
    #  - is_blocking: `extern blocking func` (a suspension source)
    is_sync: bool = False
    is_blocking: bool = False
    # Declared `unsafe`. The declaration is the obligation; the trigger rule
    # checks it against the body.
    is_unsafe: bool = False
    # Declared `consumes`: this `&var self` method ends its receiver, so the
    # call site spells `(move b).m()` and the callee performs the release. Only
    # ever true for an instance method with `&var self`.
    is_consumes: bool = False
    visibility: Visibility = Visibility.PRIVATE
    # The module that defines this method, for the cross-module member-access
    # gate. For std/builtin declarations this is a synthetic per-file id (the
    # prelude is merged into one AST for codegen, so module_path alone cannot
    # distinguish std from user code). Empty tuple = the entry/user module in
    # the non-module compilation path.
    def_module: Tuple[str, ...] = ()
    # True when this method satisfies a requirement of a conformed trait: it is
    # callable wherever the conformance is visible, so it is exempt from the
    # private-by-default method gate.
    satisfies_trait: bool = False
    # Type-param bounds from the enclosing extension, keyed by the extension's
    # type-param name (e.g. {"T": ["Copy"]} for `extension Vector<T: Copy>`).
    # A method with unmet bounds for a given instantiation does not exist there
    # (conditional conformance); the typechecker uses this to diagnose calls.
    extension_bounds: Dict[str, List[str]] = field(default_factory=dict)
    # The owning extension's declared type parameters, in the type's
    # positional order: `[U]` for `extension Pair<U>` over `struct Pair<A>`.
    # An extension may rename the parameters, and this method's signature is
    # written in its names, so a call site binding only the struct's names
    # would leave them unsubstituted. Empty for a non-generic or specialized
    # extension and for a plain function. (An `init` does not use it yet:
    # DF-251c.)
    owner_type_params: List[TypeParameter] = field(default_factory=list)
    ast_node: Optional[Any] = None  # Function or Method AST node
    # Overloading: when a name carries 2+ overloads, the mangler assigns each a
    # type-signature-suffixed codegen symbol; `mangled_name` holds it (empty for
    # a single declaration, which uses the plain name). `decl_node` is the
    # declaring AST node, stamped with the same `mangled_symbol` so codegen
    # emits the definition under it.
    mangled_name: str = ""
    decl_node: Optional[Any] = None
    # The codegen base this declaration's symbols are built from: the plain
    # name unless another module in this compilation declares a free function
    # of the same name, in which case it is `name$M$<module tag>`, since two
    # definitions cannot share one LLVM symbol. Empty means the plain name
    # (design 249).
    symbol_base: str = ""


@dataclass
class StructSymbol:
    """Symbol for a struct type."""
    kind: SymbolKind = SymbolKind.STRUCT
    fields: Dict[str, SawType] = field(default_factory=dict)
    field_order: List[str] = field(default_factory=list)
    type_params: List[TypeParameter] = field(default_factory=list)
    methods: Dict[str, FunctionSymbol] = field(default_factory=dict)
    # Overloading: name -> all overloads of that method. `methods` keeps the
    # first-registered overload as the representative for single-overload
    # lookups; overloaded call sites resolve against this list.
    method_overloads: Dict[str, List[FunctionSymbol]] = field(default_factory=dict)
    init_methods: List[FunctionSymbol] = field(default_factory=list)
    conformances: List[str] = field(default_factory=list)
    visibility: Visibility = Visibility.PRIVATE
    # Per-field effective visibility (name -> Visibility) and the module that
    # defines this struct, for the cross-module field-access gate. See
    # FunctionSymbol.def_module for the std synthetic id.
    field_visibility: Dict[str, Visibility] = field(default_factory=dict)
    def_module: Tuple[str, ...] = ()
    # This type's identity: `(def_module, name)` fused into one string
    # (`Header$m$dep`), or the plain name for a root-module or std type. It is
    # the namespace key, the codegen layout key, the monomorphization base and
    # the method-mangling receiver; `type_identity.display_name` recovers the
    # short name (design 144).
    type_identity: str = ""
    # `unsafe struct`: naming/binding/receiving/returning one of its values
    # makes a function unsafe. Held here because `ast_node` is None for a
    # non-generic struct.
    is_unsafe: bool = False
    # `borrows struct`: this type holds a lent place, so its values live only
    # inside a window and its reference field is legal. Held here for the
    # reason `is_unsafe` is, and keyed by type identity rather than
    # visibility, so a user borrowing struct in another module follows exactly
    # std's rules.
    is_borrowing: bool = False
    line: int = 0
    column: int = 0
    ast_node: Optional[Struct] = None
    # Specialized methods for specific type arguments (e.g., extension Vector<String>)
    # Key: tuple of type arg strings like ("String",), Value: method_name -> FunctionSymbol
    specialized_methods: Dict[Tuple[str, ...], Dict[str, FunctionSymbol]] = field(default_factory=dict)


@dataclass
class EnumSymbol:
    """Symbol for an enum type.

    An enum carries methods on the same terms as a struct: the method tables
    mirror `StructSymbol`'s field for field, so every lookup, overload resolver
    and visibility gate written against a struct symbol works unchanged with an
    enum symbol. Keep the two in step.
    """
    kind: SymbolKind = SymbolKind.ENUM
    variants: Dict[str, List[Tuple[str, SawType]]] = field(default_factory=dict)
    variant_order: List[str] = field(default_factory=list)
    type_params: List[TypeParameter] = field(default_factory=list)
    visibility: Visibility = Visibility.PRIVATE
    # The module that defines this enum. Read by the orphan rule (a
    # conformance is declarable only where the type or the trait is defined);
    # see FunctionSymbol.def_module for the std synthetic id.
    def_module: Tuple[str, ...] = ()
    # See StructSymbol.type_identity.
    type_identity: str = ""
    ast_node: Optional[SawEnum] = None
    # --- method surface, mirroring StructSymbol ---
    methods: Dict[str, FunctionSymbol] = field(default_factory=dict)
    method_overloads: Dict[str, List[FunctionSymbol]] = field(default_factory=dict)
    # Enums have no `init` (the cases are the constructors), so this stays
    # empty and exists only to keep the struct-shaped code paths uniform.
    # `_register_extension` rejects an `init` with a teaching error.
    init_methods: List[FunctionSymbol] = field(default_factory=list)
    conformances: List[str] = field(default_factory=list)
    specialized_methods: Dict[Tuple[str, ...], Dict[str, FunctionSymbol]] = field(default_factory=dict)
    line: int = 0
    column: int = 0
    # Raw integer backing: the declared backing type of a
    # payload-free enum (`enum E: UInt8 { ... }`), or None. When set, every case
    # carries an explicit value in `raw_values` and the enum is `as`-castable to
    # the backing with a synthesized `E.from(raw:)` inverse.
    raw_type: Optional[SawType] = None
    raw_values: Dict[str, int] = field(default_factory=dict)


@dataclass
class TraitMethodSymbol:
    """Symbol for a method signature in a trait."""
    name: str
    param_types: List[SawType] = field(default_factory=list)
    param_names: List[str] = field(default_factory=list)
    return_type: Optional[SawType] = None
    self_mutable: bool = False
    self_is_reference: bool = True
    # `sync` requirement: calls through `any` stay sync-callable.
    is_sync: bool = False
    # `unsafe` requirement: every conformer's implementation is unsafe, and so
    # is any call through the requirement.
    is_unsafe: bool = False
    # A static requirement, called on the type. There is no receiver to
    # dispatch on, which keeps a trait carrying one out of `any`.
    is_static: bool = False
    # Default method body: the parsed `TraitMethod` AST when the method
    # declares a `{ ... }` default, else None. A conformer that omits the
    # method gets a per-conformer Method synthesized from this body.
    ast_node: Optional[Any] = None
    # Declaration-time resolution. `param_types`/`return_type` above are stored
    # raw, and a raw `data.Data` or bare `Config` means whatever the declaring
    # module's imports say. These are the same signature resolved once, at
    # `_register_trait`, in that module's context. A foreign call site cannot
    # do this itself: the prelude gate would run against the wrong module.
    #
    # `None` means "not resolved" (the shallow `register_module_from_ast` path
    # builds symbols without it), and every consumer then defers the deep
    # argument check.
    resolved_param_types: Optional[List[Optional[SawType]]] = None
    resolved_return_type: Optional[SawType] = None
    # The names in this requirement's signature that stay ABSTRACT at every call
    # site: the trait's associated types (own and inherited), the trait's own
    # type parameters, and the requirement's own. A parameter whose resolved type
    # names none of them (after `Self` is substituted to the receiver) is
    # decidable and gets the ordinary argument check.
    abstract_type_names: FrozenSet[str] = frozenset()


@dataclass
class TraitSymbol:
    """Symbol for a trait."""
    kind: SymbolKind = SymbolKind.TRAIT
    name: str = ""
    methods: Dict[str, TraitMethodSymbol] = field(default_factory=dict)
    associated_types: List[str] = field(default_factory=list)
    parent_traits: List[str] = field(default_factory=list)
    visibility: Visibility = Visibility.PRIVATE
    # The module that defines this trait, the other place the orphan rule
    # permits a conformance to be declared.
    def_module: Tuple[str, ...] = ()
    # See StructSymbol.type_identity. `any Trait` erasure, conformance tables
    # and vtable symbols are all keyed by it, so a trait qualifies on the same
    # terms as a type.
    type_identity: str = ""


@dataclass
class TypeAliasSymbol:
    """Symbol for a type alias."""
    kind: SymbolKind = SymbolKind.TYPE_ALIAS
    aliased_type: Optional[SawType] = None
    visibility: Visibility = Visibility.PRIVATE
    # See StructSymbol.type_identity.
    type_identity: str = ""
    def_module: Tuple[str, ...] = ()
    # The unresolved immediate alias target (`type A = B` stores `B` verbatim,
    # possibly itself an alias). `aliased_type` collapses the whole chain to the
    # final underlying; `immediate_type` preserves one hop so the distinct-type
    # cast can distinguish a partial projection toward an ancestor
    # alias (`b as A` where `type B = A`) from a sibling-alias cast.
    immediate_type: Optional[SawType] = None


@dataclass
class StaticSymbol:
    """Symbol for a module-level `static` declaration.

    Statics are const-initialized and immortal. An immutable one is Sync-only;
    an `unsafe static var` is mutable, exempt from Sync, and makes
    every function that names it `unsafe` through the trigger rule.
    `mangled_name` is the codegen identity — the LLVM global's name, prefixed so
    it never clashes with a function of the same name in the (shared) LLVM value
    symbol table.
    """
    kind: SymbolKind = SymbolKind.STATIC
    type: Optional[SawType] = None
    mangled_name: str = ""
    visibility: Visibility = Visibility.PRIVATE
    # Declared `unsafe static var`. Assignment, `&var` lends and by-pointer
    # receivers are permitted on one and refused on every other static;
    # naming one is unsafe contact.
    is_var: bool = False
    line: int = 0
    column: int = 0
    # The module that declared this static. A private static in a non-root
    # module is nameable only from there, so it lives in the namespace's
    # per-module overlay rather than the shared simple-name slot.
    def_module: Tuple[str, ...] = ()
    # What this static means in a const-required position: the integer it
    # folds to, or the reason it folds to nothing. Carried on the symbol, not
    # looked up from the declaration, because an import may bind it under
    # another name (`import kcore.{REGION_SIZE as RS}`) and the answer has to
    # travel with it. Computed once, at registration.
    const_value: Optional[int] = None
    const_reject: Optional[str] = None
    # Whether this static's initializer was admitted as a constant at any
    # type. `const_value` answers only in the integer domain, so a `Slot`-typed
    # static needs this to be usable in `[ZERO_SLOT; N]`, a static alias, or a
    # struct-literal field. Rides the symbol for the reason `const_value` does.
    const_init: bool = False


@dataclass
class ModuleSymbol:
    """Symbol for an imported or declared module."""
    kind: SymbolKind = SymbolKind.MODULE
    # The module's own namespace containing its symbols
    namespace: Optional['Namespace'] = None
    # Original module path (e.g., ["std", "io"])
    path: List[str] = field(default_factory=list)
    # Visibility of the module itself (public module vs module)
    visibility: Visibility = Visibility.PRIVATE


# Union type for any symbol that can be resolved
Symbol = Union[FunctionSymbol, StructSymbol, EnumSymbol, TraitSymbol, TypeAliasSymbol, ModuleSymbol, StaticSymbol]


@dataclass
class VisibilityRefusal:
    """A name a qualified reach found and the visibility tier refused.

    Resolution answers None for two different facts, "no such name" and "not
    yours", and reporting the first for the second teaches nothing. A caller
    passing a `refusals` list to `Namespace.resolve` gets this instead, and can
    name the tier and the module that owns it.

    `module_label` is the defining module's dotted path (where a reader must
    go to change the modifier), not the module the name was found through.
    """
    name: str
    visibility: Visibility
    module_label: str


class Namespace:
    """Unified symbol table for all declarations.

    This consolidates all type/function/method lookups into a single
    source of truth that both the type checker and code generator use.
    """

    # True only on the per-std-file view below. A bare-name
    # cross-module fallback consults it to leave std's qualified-only surface
    # out of the bare-name search.
    is_std_leaf: bool = False

    def __init__(self, module_path: Tuple[str, ...] = ()):
        # Module path this namespace belongs to (e.g., ("modules", "utils"))
        self.module_path: Tuple[str, ...] = module_path

        # Package root for public(package) visibility (e.g., () for top-level)
        self.package_root: Tuple[str, ...] = ()

        # The top-level names bound by `--module-path name=dir`, one per
        # package. `visibility_relation_allows` roots `public(package)` at
        # `(name,)` for a symbol defined under one, as it roots std at
        # `("<std>",)`. It lives here, not only on the typechecker, because the
        # qualified-reach decision is made in this layer
        # (`_resolve_parts.is_visible`). Stamped by `TypeChecker.check_module`
        # on every module namespace it builds, and inherited wherever
        # `package_root` is inherited.
        self.mapped_packages: FrozenSet[str] = frozenset()

        # Module path -> package identity, for every module this compile
        # loaded. A mapped package and std are decided by the module path alone
        # (`package_identity` below); everything else depends on where the file
        # lives (its `Saw.toml` root, or the entry file's tree), which only the
        # driver can compute, so it is handed in. On a namespace nobody
        # stamped, `package_identity` answers None and the funnel reads that as
        # "not the same package": fail closed, or `public(package)` would be
        # advisory across relative-path imports.
        self.package_identities: Dict[Tuple[str, ...], str] = {}

        # Core symbol tables
        self.functions: Dict[str, FunctionSymbol] = {}
        # Overloading: name -> all free-function overloads. The `functions` map
        # above keeps the first-registered overload as the representative;
        # overloaded call sites resolve against this list.
        self.function_overloads: Dict[str, List[FunctionSymbol]] = {}
        # Free functions have module identity, in two separate acts (as types
        # do):
        #   1. Storage, keyed by (defining module, name). Two modules' `encode`s
        #      are two entries that never collide, so the declaration-site
        #      ambiguity check compares same-module declarations only.
        #   2. Binding: `function_overloads` above is the name-as-written view
        #      of this namespace, and `function_name_modules` records which
        #      defining modules each bare name is bound to here. A name may
        #      bind to several modules, since free functions overload, unlike a
        #      type name, which is simply ambiguous.
        # Root module = the empty key, as in `module_statics` (design 249).
        self.module_function_overloads: Dict[
            Tuple[str, ...], Dict[str, List[FunctionSymbol]]] = {}
        self.function_name_modules: Dict[str, List[Tuple[str, ...]]] = {}
        # The four type tables are keyed by module-qualified type identity
        # (`Header$m$dep`), not the bare source name. Two modules' private
        # `Header`s are two entries, hence two layouts, two monomorphizations
        # and two method families. `type_names` below is the name -> identity
        # view a source reference resolves through (design 144).
        self.structs: Dict[str, StructSymbol] = {}
        self.enums: Dict[str, EnumSymbol] = {}
        self.traits: Dict[str, TraitSymbol] = {}
        self.type_aliases: Dict[str, TypeAliasSymbol] = {}
        self.modules: Dict[str, ModuleSymbol] = {}
        # How a bare name spelled in this namespace's source resolves, keyed by
        # the name as written: the declaration's own name, or the local name
        # an `import a.{Header as Hdr}` bound (a pure local rename, so the
        # identity is unchanged). Root-module and std types map to themselves.
        self.type_names: Dict[str, str] = {}
        # The same view for names only one module may write: a std file's
        # file-private types, keyed by that file's module then by name. A
        # private std type must not occupy the shared slot above, or every
        # internal std type would be a reserved word for every program. The
        # type counterpart of `module_statics`, read through the same
        # accessor-module-first rule (design 204).
        self.module_type_names: Dict[Tuple[str, ...], Dict[str, str]] = {}
        # Source label (module path string) each type name was first bound
        # from, and the names bound to two different identities. A bare
        # reference to an ambiguous name is a use-site error; the binding stays
        # first-wins so the diagnostic is raised once, where the author wrote
        # the name.
        self.type_provenance: Dict[str, str] = {}
        self.ambiguous_types: Dict[str, Tuple[str, str, str]] = {}
        # The type names the builtin merge bound here: the prelude core plus
        # the std names an import gate keeps hidden. An ambient binding is not
        # this file naming something, and `bind_type_name` must tell them
        # apart: an explicit import shadows a gated std name instead of tying
        # with it, and a remaining collision names a real module instead of
        # `<unknown>`. Filled by `note_builtin_type_bindings`; a name leaves the
        # set once something in this file claims it (design 255).
        self.builtin_type_names: Set[str] = set()
        # Module-level `static` declarations, keyed by simple name. Holds only
        # the statics a simple name may resolve to from any module: the public
        # ones, plus the root module's own. See `module_statics` for the rest.
        self.statics: Dict[str, StaticSymbol] = {}
        # Module-private statics of a non-root module, keyed by defining module
        # then simple name. A private static is unnameable outside its module,
        # so it must not occupy the shared `statics` slot, or every private std
        # constant (`SEEK_SET`, ...) would be a reserved word for every program.
        self.module_statics: Dict[Tuple[str, ...], Dict[str, StaticSymbol]] = {}

        # Type conformances: type_name -> {trait_name -> {assoc_type_name -> SawType}}
        self.conformances: Dict[str, Dict[str, Dict[str, SawType]]] = {}

        # Memo for `struct_is_cell_carrying`, asked once per method declaration
        # and once per method body so the two always agree.
        self._cell_carrying_by_name: Dict[str, bool] = {}

        # The declared thread-safety assertions (design 186).
        #   type name -> {"UnsafeSend" | "UnsafeSync" -> [[bound, ...], ...]}
        # The inner list is positional over the type's own type parameters, so a
        # conditional header (`extension Vector<T: Send, A: Send>: UnsafeSend`)
        # is re-checked against each instantiation's arguments rather than taken
        # on faith. Kept apart from `conformances` because these two are read by
        # `_send_sync` on every query and must never be confused with an
        # ordinary conformance lookup.
        self.thread_assertions: Dict[str, Dict[str, list]] = {}

        # Generic AST storage for instantiation
        self.generic_functions: Dict[str, Function] = {}
        self.generic_structs: Dict[str, Struct] = {}
        self.generic_enums: Dict[str, SawEnum] = {}
        self.generic_extensions: Dict[str, List[Extension]] = {}

        # Tracks which monomorphized instantiations have been generated
        self.instantiated: set = set()

        # Accessibility tracking for imports.
        # Symbols directly accessible without qualification
        self.directly_accessible: Set[str] = set()
        # If True, all symbols are accessible (non-module mode)
        self.allow_all_access: bool = True

        # Provenance for merge collision reporting: symbol name -> source label
        # (e.g. a module path string). Populated by merge_into when a source
        # label is supplied; used to name both sides of an ambiguity.
        self._provenance: Dict[str, str] = {}

        # --- export control (design 229) -------------------------------------
        # An import is private by default: an importer of this module reaches
        # the names it declares public and the ones it re-exports with
        # `public import`, and nothing more. These two tables are what an
        # ordinary import bound (bare names, module qualifiers), each mapped to
        # its source path, so a refused reach can name the dependency the
        # reader should import directly.
        self.import_private_names: Dict[str, str] = {}
        self.import_private_modules: Dict[str, str] = {}
        # The glob imports this namespace was built from: (label, source
        # namespace). A glob binds no qualifier, so `modules` does not record it
        # — and a bare name refused because the globbed module only imports it
        # would otherwise have no way to say so.
        self.glob_sources: List[Tuple[str, 'Namespace']] = []
        # The selective imports, on the same terms. A selective import binds
        # the names it lists and no qualifier, so it is not in `modules`, yet
        # two questions still need its source: whether a conformance declared
        # there is visible here (the orphan rule makes conformances coherent
        # program-wide, so no import form may lose one), and which module hides
        # a bare name this file cannot reach. Both read this list beside
        # `glob_sources`.
        self.selective_sources: List[Tuple[str, 'Namespace']] = []
        # The qualifiers this file's selective and glob imports do not bind:
        # leaf -> (module path, form word). Nothing resolves through it; it
        # lets the refusal at an unbound qualifier name the whole-module import
        # line that would bind it.
        self.nonbinding_qualifiers: Dict[str, Tuple[str, str]] = {}

        # --- the import gate's tables, wired in from outside -----------------
        # Filled by `sawc.py` on the builtin namespace once std has been
        # parsed, and read from there by the gate. They are declared here
        # rather than grafted on at runtime (the astgraft lane's rule).
        #
        # Std file leaf -> the symbols that file defines (the set
        # `import std.data.*` exposes bare), and its inverse.
        self._std_file_symbols: Dict[str, Set[str]] = {}
        self._std_symbol_file: Dict[str, str] = {}
        # The same two over every top-level declaration, not just the surface:
        # a std file's private types are excluded from the pair above so
        # nothing user-facing reaches them, but the codegen exclusion still
        # has to account for them. `_std_file_keys` holds each declaration's
        # codegen key (its type identity), which is what the tables use.
        self._std_file_all_names: Dict[str, Set[str]] = {}
        self._std_file_keys: Dict[str, Set[str]] = {}
        # The declaration-only subset of the above: traits and type aliases,
        # which emit no code and which `_filter_std_ast` keeps whatever leaf
        # they came from. The codegen exclusion reads this so naming one does
        # not drag its whole module into the program.
        self._std_file_decl_only_names: Dict[str, Set[str]] = {}
        # The std modules and symbols that require an import (the non-prelude
        # surface). Constants from `sawc.py`, not per-namespace state.
        self._import_required_modules: Set[str] = set()
        self._import_required_symbols: Set[str] = set()

    # =========================================================================
    # Unified Resolution
    # =========================================================================
    #
    # The export gate (design 229): one predicate, named entry points.
    #
    # "Can an importer of module M reach the name X through M?" must hold at
    # every spelling that crosses a module boundary. The one decision
    # procedure is `hidden_import`. ENTRY POINTS:
    #
    #   * `_resolve_parts` under `through_import=True` — the qualified reach
    #     (`m.X`, each chain hop `m.q.X`); typechecker callers reach it via
    #     `resolve(..., through_import=True)` on the foreign namespace.
    #   * `TypeChecker._resolve_qualified_symbol` (typechecker/types.py) — the
    #     qualified-type walk, gating each module hop itself.
    #   * `TypeChecker.check_module` glob and selective import branches — the
    #     bare reach: skipped (glob) or refused with a diagnostic (selective).
    #   * `TypeChecker._cross_module_lookup` (typechecker/types.py) and
    #     `_check_function_call`'s imported-function fallback
    #     (typechecker/expressions.py) — the bare-name searches.
    #   * `TypeChecker._import_hiding`, `_not_reexported_hint`,
    #     `_module_selectable_names`, `_report_qualified_not_reexported`
    #     (typechecker/core.py) — diagnostics naming the module that hid it.
    #
    # A module's own view is never gated: `through_import` is False for the
    # namespace the checked code lives in, so the rule governs what flows
    # through a module, not what it sees.
    # =========================================================================

    def hidden_import(self, name: str, as_module: bool = False) -> Optional[str]:
        """The path `name` was imported from, when this module merely imports it.

        Returns the source path (`std.file`, `dep.wire`) for a name an ordinary
        `import` bound here — the reach an importer must be refused, and the
        dependency the diagnostic tells them to import directly. None when the
        name is this module's own, was re-exported with `public import`, or is
        not bound here at all.

        `as_module` asks the question of a module qualifier instead of a bare
        name; the two live in different tables and a program may legitimately
        use one spelling for both.
        """
        table = self.import_private_modules if as_module else self.import_private_names
        return table.get(name)

    def note_private_import(self, name: str, source: str, as_module: bool = False):
        """Record that an ordinary (non-`public`) import bound `name` here."""
        table = self.import_private_modules if as_module else self.import_private_names
        table.setdefault(name, source)

    def resolve(self, path: str, check_access: bool = True,
                check_visibility: bool = False,
                accessor_module: Optional[Tuple[str, ...]] = None,
                through_import: bool = False,
                refusals: Optional[List['VisibilityRefusal']] = None
                ) -> Optional['Symbol']:
        """
        Resolve a symbol path to its definition.

        Handles both simple names ("Point") and qualified names ("utils.Point").

        Args:
            path: A symbol path, either simple ("foo") or dotted ("mod.foo")
            check_access: If True, verify the symbol is accessible (respects imports)
            check_visibility: If True, check visibility rules for cross-module access
            accessor_module: The module path of the code doing the lookup (for visibility)
            through_import: True when the lookup reaches into this namespace
                from a module that imports it (the export gate, above).
            refusals: Optional out-list. A name refused by its visibility tier
                appends a `VisibilityRefusal`, so the diagnostic can say "`X`
                is public(package) in `pkg.mod`" instead of "has no symbol
                `X`". An absent name appends nothing.

        Returns:
            The resolved Symbol, or None if not found or not accessible
        """
        parts = path.split('.') if '.' in path else [path]
        return self._resolve_parts(parts, check_access, check_visibility,
                                   accessor_module, through_import, refusals)

    def _resolve_parts(self, parts: List[str], check_access: bool = True,
                       check_visibility: bool = False,
                       accessor_module: Optional[Tuple[str, ...]] = None,
                       through_import: bool = False,
                       refusals: Optional[List['VisibilityRefusal']] = None
                       ) -> Optional['Symbol']:
        """Resolve a list of path components to a symbol.

        Args:
            parts: Path components to resolve
            check_access: If True, verify the symbol is directly accessible (import checking)
            check_visibility: If True, check visibility rules for cross-module access
            accessor_module: The module path of the code doing the lookup
            through_import: See `resolve`. Set on every hop into a module's
                namespace, so a chain (`m.q.X`) is gated at each level.
            refusals: See `resolve`. Carried through every hop, so the reason a
                chain failed is the reason its last hop failed.
        """
        if not parts:
            return None

        name = parts[0]
        remaining = parts[1:]

        # This namespace belongs to a module someone else imports, and `name`
        # is one that module merely imports itself: not part of its surface,
        # under either spelling.
        if through_import and self.hidden_import(name, as_module=bool(remaining)):
            return None

        # If there are remaining parts, first component must be a module
        if remaining:
            if name in self.modules:
                module = self.modules[name]
                # Check module visibility before allowing access
                if check_visibility and hasattr(module, 'visibility'):
                    acc_mod = accessor_module if accessor_module is not None else ()
                    if not self._symbol_visible(module, name, acc_mod,
                                                refusals):
                        return None  # Module not visible
                if module.namespace:
                    # Cross-module access: check visibility with accessor
                    # context, and the export gate, since everything past the
                    # first hop is reached through a module.
                    #
                    # An accessor of `()` is the entry module, not "unknown",
                    # so test against None: falling back to this module's own
                    # path would make every chain hop a same-module access.
                    return module.namespace._resolve_parts(
                        remaining, check_access=False, check_visibility=True,
                        accessor_module=(accessor_module
                                         if accessor_module is not None
                                         else self.module_path),
                        through_import=True, refusals=refusals
                    )
            return None

        # Single name - check accessibility (import-based)
        if check_access and not self.allow_all_access:
            if name not in self.directly_accessible and name not in self.modules:
                # Name exists but isn't directly accessible
                return None

        # Helper to check visibility using proper module paths
        def is_visible(symbol) -> bool:
            if not check_visibility:
                return True
            if not hasattr(symbol, 'visibility'):
                return True
            acc_mod = accessor_module if accessor_module is not None else ()
            return self._symbol_visible(symbol, name, acc_mod, refusals)

        # Check all symbol tables
        # Order: modules first (for qualified access), then types, then functions
        if name in self.modules:
            module = self.modules[name]
            # Check module visibility before returning
            if not is_visible(module):
                return None  # Module not visible from accessor
            return module

        for _table_lookup in (self.lookup_struct, self.lookup_enum,
                              self.lookup_trait, self.lookup_type_alias):
            sym = _table_lookup(name)
            if sym is not None:
                return sym if is_visible(sym) else None
        if name in self.functions:
            sym = self.functions[name]
            return sym if is_visible(sym) else None
        static_sym = self.get_static(name, accessor_module)
        if static_sym is not None:
            return static_sym if is_visible(static_sym) else None

        return None

    def _symbol_visible(self, symbol, name: str,
                        accessor_module: Tuple[str, ...],
                        refusals: Optional[List['VisibilityRefusal']]) -> bool:
        """Whether `accessor_module` may reach `symbol` found in this namespace,
        recording the refusal when it may not.

        The relation is asked about the symbol's own `def_module`, not this
        namespace's path. A re-exported symbol is the same object its defining
        module declared, so the tier rides the symbol; judging it by where it
        was found would let a `public import` republish a package-private name.
        Module qualifiers carry no `def_module` (a qualifier is a member of the
        namespace holding it), so they fall back to this module's path.
        """
        def_module = tuple(getattr(symbol, 'def_module', ()) or ()) \
            or self.module_path
        if self.visibility_relation_allows(
                def_module, symbol.visibility, accessor_module):
            return True
        if refusals is not None:
            label = '.'.join(def_module) if def_module else "<entry>"
            refusals.append(
                VisibilityRefusal(name, symbol.visibility, label))
        return False

    def make_accessible(self, name: str):
        """Mark a symbol as directly accessible (without qualification)."""
        self.directly_accessible.add(name)

    def make_all_accessible(self, names: List[str]):
        """Mark multiple symbols as directly accessible."""
        self.directly_accessible.update(names)

    def enable_import_checking(self):
        """Enable import-based accessibility checking."""
        self.allow_all_access = False

    def is_accessible(self, name: str) -> bool:
        """Check if a simple name is directly accessible."""
        if self.allow_all_access:
            return True
        return name in self.directly_accessible or name in self.modules

    def resolve_type(self, path: str) -> Optional['Symbol']:
        """Resolve a path that should be a type (struct, enum, or type alias)."""
        symbol = self.resolve(path)
        if symbol and symbol.kind in (SymbolKind.STRUCT, SymbolKind.ENUM, SymbolKind.TYPE_ALIAS):
            return symbol
        return None

    def resolve_callable(self, path: str) -> Optional['Symbol']:
        """Resolve a path that should be callable (function or struct init)."""
        symbol = self.resolve(path)
        if symbol and symbol.kind in (SymbolKind.FUNCTION, SymbolKind.STRUCT):
            return symbol
        return None

    # =========================================================================
    # Registration Methods
    # =========================================================================

    def register_function(self, name: str, symbol: FunctionSymbol):
        """Register a function symbol, appending it to the overload set.

        The first registration under a name is also the representative in
        `self.functions`; later overloads only extend `function_overloads`.

        The same act files the symbol under its identity (defining module,
        name) and binds `name` here to that module. ENTRY POINTS (every
        registration path, so the binding view is complete):
          * `_register_function` / `_register_extern_function` — own declarations
          * `register_bare_function` — glob, selective, std expose and
            parent-module import binding
          * `_std_leaf_namespace` — the per-std-file qualifier view
          * `register_module_from_ast` — the module-AST shim below
        """
        self.function_overloads.setdefault(name, []).append(symbol)
        key = tuple(getattr(symbol, 'def_module', ()) or ())
        bucket = self.module_function_overloads.setdefault(key, {})
        filed = bucket.setdefault(name, [])
        # By identity: `FunctionSymbol` compares by value, and two declarations
        # are two declarations however alike their fields look.
        if not any(s is symbol for s in filed):
            filed.append(symbol)
        self.bind_function_module(name, key)
        if name not in self.functions:
            self.functions[name] = symbol

    def register_bare_function(self, name: str, symbol: FunctionSymbol):
        """Bind an already-declared function symbol under the bare `name` here.

        An import binds the whole overload set, not the representative, so a
        call only a sibling matches still resolves. Idempotent by object
        identity, so two import lines naming one module bind each member once.
        Callers: the glob, selective and parent-module binding arms of
        `TypeChecker.check_module`, and `_process_std_import`."""
        decl = getattr(symbol, 'decl_node', None)
        for bound in self.function_overloads.get(name, ()):
            # Identity, or the same declaration behind an aliasing copy
            # (`import m.{f as g}` binds a `dataclasses.replace` of the symbol).
            if bound is symbol or (
                    decl is not None
                    and getattr(bound, 'decl_node', None) is decl):
                return
        self.register_function(name, symbol)

    def bind_function_module(self, name: str, module: Tuple[str, ...]):
        """Bind the bare spelling `name` to `module`'s free functions here.

        `register_function` calls it for every symbol it files; the std import
        path calls it directly, because an unaliased
        `import std.json.*` binds a name whose symbol is already present (the
        builtin namespace is merged wholesale into every module) and so never
        re-registers it.
        """
        bound = self.function_name_modules.setdefault(name, [])
        if module not in bound:
            bound.append(module)

    def lookup_module_function_overloads(
            self, name: str,
            module: Tuple[str, ...]) -> List[FunctionSymbol]:
        """The overloads `module` itself declares under `name`.

        The identity-keyed read: it answers about one module's declarations,
        never about what that module imported. Callers:
          * `_register_function` — the declaration-site ambiguity check
          * `_std_leaf_namespace` — the per-std-file qualifier view
          * `_process_std_import._expose` — the aliasing std import
        `_stamp_overload_symbols` and `merge_into` walk the table directly
        rather than query it."""
        return self.module_function_overloads.get(tuple(module), {}).get(name, [])

    def lookup_function_overloads(
            self, name: str,
            accessor_module: Optional[Tuple[str, ...]] = None
            ) -> List[FunctionSymbol]:
        """The free-function lookup funnel (design 249).

        Returns the overloads a reference to the bare `name` resolves against
        in this namespace: the accessor module's own declarations plus the
        names imported bare into it. When several modules bind one name, the
        merged set is the overload set; a genuine tie is the ambiguity error
        at the call, naming both origins. The filter engages only when the
        candidates span two or more defining modules.

        ENTRY POINTS (every reader of the free-function registry goes through
        here or through `lookup_module_function_overloads` above):
          - `_check_function_call` — the bare call (typechecker/expressions.py)
          - `_check_module_qualified_call`'s two arms — `q.f(...)` and the
            chained `a.b.f(...)`, each asking the NAMED module's namespace
          - `_check_funcpointer_named_function` + `_check_identifier`'s
            FuncPointer arm — a named function in a `FuncPointer<F>` slot
          - `_reinterpret_struct_init_as_call` — the labeled-call reroute
          - `check_module`'s bare-binding arms — the glob, the selective
            import and the parent-module inherit, each asking the source
            namespace for the whole set a name stands for
          - `lookup_function` below, which is how every single-symbol reader
            (`get_function_info` and its callers) sees the same answer
        """
        cands = self.function_overloads.get(name, [])
        if len(cands) < 2:
            return cands
        modules = {tuple(getattr(s, 'def_module', ()) or ()) for s in cands}
        if len(modules) < 2:
            return cands
        # A name several modules define is visible here only through the
        # modules this namespace bound it from, plus the accessor's own
        # declarations and the root/builtin module. Fail closed: an unbound
        # name resolves to nothing, so the caller reports "must be imported"
        # rather than silently picking a module the source never named.
        allowed = set(self.function_name_modules.get(name, ()))
        allowed.add(())
        if accessor_module is not None:
            allowed.add(tuple(accessor_module))
        allowed.add(self.module_path)
        return [s for s in cands
                if tuple(getattr(s, 'def_module', ()) or ()) in allowed]

    @staticmethod
    def _static_is_module_local(symbol: 'StaticSymbol') -> bool:
        """Whether `symbol` belongs in the per-module overlay rather than the
        shared simple-name slot: a private static of a non-root module, which
        no other module can name."""
        return (symbol.visibility == Visibility.PRIVATE
                and bool(getattr(symbol, 'def_module', ()) or ()))

    def register_static(self, name: str, symbol: 'StaticSymbol'):
        """Register a module-level static symbol.

        A module-private static goes to its own module's overlay; everything
        else takes the shared slot."""
        if self._static_is_module_local(symbol):
            key = tuple(symbol.def_module)
            self.module_statics.setdefault(key, {})[name] = symbol
        else:
            self.statics[name] = symbol

    def has_static(self, name: str,
                   module: Optional[Tuple[str, ...]] = None) -> bool:
        """Whether a static named `name` is visible to code in `module`."""
        return self.get_static(name, module) is not None

    def get_static(self, name: str,
                   module: Optional[Tuple[str, ...]] = None
                   ) -> Optional['StaticSymbol']:
        """Look up a static by simple name, as seen from `module`.

        The accessor module's own private statics win over the shared slot, so a
        std file keeps reading its own `ASCII_ZERO` even when the program being
        compiled declares one too."""
        own = self.module_statics.get(tuple(module or ()))
        if own is not None and name in own:
            return own[name]
        return self.statics.get(name)

    # =========================================================================
    # Type registration and name binding (design 144)
    #
    # Two separate acts, which must stay separate:
    #   1. The symbol is stored under its identity. Two modules' `Header`s are
    #      two entries that can never overwrite each other.
    #   2. The name as written is bound to that identity in this namespace's
    #      `type_names` view. That binding is per-namespace, so `Header` means
    #      dep's Header inside dep and the entry's Header inside the entry.
    # =========================================================================

    @staticmethod
    def _identity_of(name: str, symbol) -> str:
        """`symbol`'s identity, defaulting to the name it is registered under.

        The default covers every symbol built outside the typechecker's
        registration pass — builtins, the module-AST shim below — none of which
        belongs to a qualifying module."""
        return getattr(symbol, 'type_identity', "") or name

    @staticmethod
    def _type_is_module_local(symbol, identity: str) -> Optional[Tuple[str, ...]]:
        """The module whose private name view `identity` belongs in, or None.

        Mirrors `_static_is_module_local`: a std file's private type is
        nameable only from that file, so its binding lives in the per-module
        overlay rather than the shared simple-name slot."""
        from type_identity import is_module_local
        module = tuple(getattr(symbol, 'def_module', ()) or ())
        return module if is_module_local(identity, module) else None

    def _own_module_label(self) -> str:
        """This namespace's own module, spelled the way a reader would write it.

        The label a binding made here carries, so a collision report names both
        sides. The entry module has no path to spell."""
        module = tuple(self.module_path or ())
        if not module:
            return "this module"
        if module[:1] == ("<std>",):
            return "std." + ".".join(module[1:])
        return ".".join(module)

    def note_builtin_type_bindings(self, builtin_ns):
        """Mark every type name the builtin merge just bound here as ambient,
        and give it a real source label (design 255).

        Called once per namespace, straight after `merge_into(builtin_ns)` and
        the accessibility copy, so `type_names` still holds exactly what the
        merge put there. The label distinguishes the two ambient tiers: a
        prelude name is in scope with nothing written, and a gated one needs
        `import std.<leaf>` before a program may write it. `bind_type_name`
        shadows the second and reports a collision with the first."""
        symbol_file = getattr(builtin_ns, '_std_symbol_file', {}) or {}
        for name in self.type_names:
            self.builtin_type_names.add(name)
            leaf = symbol_file.get(name)
            if leaf is None:
                label = "the prelude"
            elif name in self.directly_accessible:
                label = "std.%s (prelude)" % leaf
            else:
                label = "std.%s" % leaf
            self.type_provenance.setdefault(name, label)

    def _hide_ambient_type(self, identity: str):
        """Forget the ambient std entries this namespace merged in under
        `identity`, because a shadowing binding supersedes them here.

        The counterpart of `hide_struct`: the type tables are keyed by identity
        and `_lookup_type` consults them before the name view, so rebinding
        `type_names` alone would leave the spelling answering with the std
        symbol. std's public types are unqualified, so their identity is the
        spelling.

        A qualified identity is left alone: it is unreachable by the spelling
        anyway, and it may be one the compiler itself emits references to
        (`COMPILER_EMITTED_STD_TYPES`), which must keep resolving whatever a
        user program names its own types. Every namespace owns its tables, so
        the removal is local to this module's view."""
        if not identity or is_qualified(identity):
            return
        self.structs.pop(identity, None)
        self.enums.pop(identity, None)
        self.traits.pop(identity, None)
        self.type_aliases.pop(identity, None)
        self.conformances.pop(identity, None)

    def _shadows_ambient_binding(self, local: str) -> bool:
        """Whether binding `local` here shadows an ambient std name rather than
        colliding with it (design 255).

        Both must hold: the current binding was made by the builtin merge and
        nothing in this file has claimed the name since, and std keeps the
        name behind an import gate. That is the weakest bare-name tier, so
        `import mine.{Thread}` gets the author's type, as declaring
        `struct Thread` does (`rebind_type_name`).

        A prelude name is not shadowed: redeclaring one is a redefinition
        error (conformance row B12), and an import must not win where a
        declaration is refused. Nor is a name an earlier import bound: two
        explicit imports of one name are ambiguous at the use site."""
        return (local in self.builtin_type_names
                and local not in self.directly_accessible)

    def bind_type_name(self, local: str, identity: str, category: str = "type",
                       source_label: Optional[str] = None,
                       module_local: Optional[Tuple[str, ...]] = None):
        """Bind the source-visible name `local` to `identity` here.

        First-wins, like every other binding in this namespace, with one
        exception: a binding over an ambient gated std name shadows it
        (`_shadows_ambient_binding`). Otherwise a second binding to a different
        identity is recorded in `ambiguous_types` rather than dropped: the name
        is ambiguous at any bare use, an error raised once where it is written.

        `module_local` diverts the binding into that module's own view: two std
        files may each bind `State`, and neither binding is visible to a user
        program or to the other file.
        """
        if module_local:
            self.module_type_names.setdefault(
                tuple(module_local), {}).setdefault(local, identity)
            return
        prev = self.type_names.get(local)
        if prev is None:
            self.type_names[local] = identity
            if source_label is not None:
                self.type_provenance[local] = source_label
            return
        if prev == identity or local in self.ambiguous_types:
            return
        if self._shadows_ambient_binding(local):
            self._hide_ambient_type(prev)
            self.rebind_type_name(local, identity)
            if source_label is not None:
                self.type_provenance[local] = source_label
            return
        self.ambiguous_types[local] = (
            category,
            self.type_provenance.get(local, "<unknown>"),
            source_label if source_label is not None
            else self._own_module_label(),
        )

    def register_struct(self, name: str, symbol: StructSymbol,
                        source_label: Optional[str] = None):
        """Register a struct symbol under its identity, bound to `name`."""
        identity = self._identity_of(name, symbol)
        self.structs[identity] = symbol
        self.bind_type_name(name, identity, "struct", source_label,
                            self._type_is_module_local(symbol, identity))

    def register_enum(self, name: str, symbol: EnumSymbol,
                      source_label: Optional[str] = None):
        """Register an enum symbol under its identity, bound to `name`."""
        identity = self._identity_of(name, symbol)
        self.enums[identity] = symbol
        self.bind_type_name(name, identity, "enum", source_label,
                            self._type_is_module_local(symbol, identity))

    def rebind_type_name(self, local: str, identity: str):
        """Point the spelling `local` at `identity` here, replacing whatever it
        was bound to and clearing any ambiguity recorded for it.

        `bind_type_name` is first-wins, which is right for two imports racing
        for a name. This is the other case: the module declares `local` itself,
        over a hidden std name it never imported, so the spelling is the
        module's. It matters when a std declaration's identity differs from
        its spelling (the compiler-emitted types); first-wins would make the
        user's declaration read as an ambiguity instead of a shadow.

        Callers: type registration for a declaration, and `bind_type_name` when
        an explicit import lands on an ambient gated std name. The name leaves
        `builtin_type_names` either way, so a later binding collides normally
        rather than shadowing again."""
        self.type_names[local] = identity
        self.ambiguous_types.pop(local, None)
        self.builtin_type_names.discard(local)
        self.type_provenance[local] = self._own_module_label()

    def hide_type_conformances(self, identity: str):
        """Forget the conformances this namespace merged in for `identity`,
        because a declaration here supersedes the type that had them.

        The hidden-std shadow replaces the symbol (a user `struct Once`
        overwrites the merged entry), but the conformance table is keyed
        separately, so without this the user's type would inherit std's
        conformances (`Once: NoCopy`). The user type registers its own
        conformances a pass later, so clearing here loses nothing of theirs."""
        self.conformances.pop(identity, None)

    def hide_struct(self, identity: str):
        """Drop a struct entry this namespace merged in, because a declaration
        of the same name in another category supersedes it here.

        The hidden-std shadow works by overwrite when both are structs (the
        user symbol lands on the same identity key). Across categories there
        is no overwrite: registering an enum would leave the merged struct in
        place for `lookup_struct` to find. Every namespace owns its tables
        (`merge_into` copies entries), so the removal is local to this
        module's view."""
        self.structs.pop(identity, None)

    def register_trait(self, name: str, symbol: TraitSymbol,
                       source_label: Optional[str] = None):
        """Register a trait symbol under its identity, bound to `name`."""
        identity = self._identity_of(name, symbol)
        self.traits[identity] = symbol
        self.bind_type_name(name, identity, "trait", source_label,
                            self._type_is_module_local(symbol, identity))

    def register_type_alias(self, name: str, symbol: TypeAliasSymbol,
                            source_label: Optional[str] = None):
        """Register a type alias symbol under its identity, bound to `name`."""
        identity = self._identity_of(name, symbol)
        self.type_aliases[identity] = symbol
        self.bind_type_name(name, identity, "type alias", source_label,
                            self._type_is_module_local(symbol, identity))

    def _iter_types(self, table: Dict[str, Any]):
        """`(source name, identity, symbol)` for every type nameable here.

        Iterating the table directly would yield identities, which is the wrong
        key for anything that re-binds a name in another namespace (an import
        binds `Header`, never `Header$m$dep`). Iterating `type_names` gives the
        spellings, one entry per way the type can be written here."""
        for name, identity in list(self.type_names.items()):
            sym = table.get(identity)
            if sym is not None:
                yield name, identity, sym

    def iter_structs(self):
        return self._iter_types(self.structs)

    def iter_enums(self):
        return self._iter_types(self.enums)

    def iter_traits(self):
        return self._iter_types(self.traits)

    def resolve_type_identity(self, name: str,
                              module: Optional[Tuple[str, ...]] = None) -> str:
        """The identity a bare `name` refers to here, or `name` itself.

        Total by design: an unknown name resolves to itself, so every caller
        that only wants to canonicalize can call this unconditionally.

        `module` is the module doing the looking. Its own private type names
        win over the shared view, so `std/once.saw` keeps reading its own
        `State` even when another std file and the program each declare one;
        the same precedence `get_static` gives a module-private static."""
        if not name:
            return name
        if module:
            own = self.module_type_names.get(tuple(module))
            if own is not None and name in own:
                return own[name]
        return self.type_names.get(name, name)

    def register_module(self, alias: str, symbol: ModuleSymbol):
        """Register a module symbol (for imports)."""
        self.modules[alias] = symbol

    def register_module_from_ast(self, alias: str, module_ast: 'Program', path: List[str] = None,
                                  visibility: Visibility = Visibility.PUBLIC,
                                  module_map: dict = None):
        """
        Create and register a module from a parsed AST.

        This builds a namespace from the module's declarations and registers
        it under the given alias.

        Args:
            alias: The local name for the module (e.g., "utils")
            module_ast: The parsed Program AST for the module
            path: The original module path (e.g., ["modules", "utils"])
            visibility: The visibility of the module itself (PUBLIC for imports,
                       depends on declaration for module declarations)
            module_map: Dict of module_path_tuple -> AST for resolving imports
        """
        # Create a namespace for the module with its path
        mod_path = tuple(path) if path else ()
        mod_ns = Namespace(module_path=mod_path)
        mod_ns.package_root = self.package_root  # Inherit package root
        # And the package names and identities: without them the namespace
        # would decide `public(package)` with no root at all.
        mod_ns.mapped_packages = self.mapped_packages
        mod_ns.package_identities = self.package_identities

        # Register all symbols from the module AST
        for struct in module_ast.structs:
            fields = {f.name: f.type for f in struct.fields}
            field_order = [f.name for f in struct.fields]
            mod_ns.register_struct(struct.name, StructSymbol(
                fields=fields,
                field_order=field_order,
                type_params=struct.type_params,
                visibility=struct.visibility,
                is_unsafe=getattr(struct, 'is_unsafe', False),
                line=struct.line,
                column=struct.column,
                ast_node=struct if struct.type_params else None
            ))

        for enum in module_ast.enums:
            variants = {}
            variant_order = []
            for variant in enum.variants:
                variant_order.append(variant.name)
                variants[variant.name] = [(at.name, at.type) for at in variant.associated_types]
            mod_ns.register_enum(enum.name, EnumSymbol(
                variants=variants,
                variant_order=variant_order,
                type_params=enum.type_params,
                visibility=enum.visibility,
                ast_node=enum if enum.type_params else None
            ))

        for func in module_ast.functions:
            param_types = [p.type for p in func.parameters]
            param_names = [p.name for p in func.parameters]
            mod_ns.register_function(func.name, FunctionSymbol(
                param_types=param_types,
                param_names=param_names,
                return_type=func.return_type,
                type_params=func.type_params,
                visibility=func.visibility,
                is_unsafe=getattr(func, 'is_unsafe', False),
                ast_node=func if func.type_params else None
            ))

        for trait in module_ast.traits:
            methods = {}
            assoc_types = []
            for m in trait.methods:
                methods[m.name] = TraitMethodSymbol(
                    name=m.name,
                    param_types=[p.type for p in m.parameters],
                    param_names=[p.name for p in m.parameters],
                    return_type=m.return_type,
                    self_mutable=m.self_mutable
                )
            for at in trait.associated_types:
                assoc_types.append(at.name)
            mod_ns.register_trait(trait.name, TraitSymbol(
                methods=methods,
                associated_types=assoc_types,
                visibility=trait.visibility
            ))

        # Register inline module declarations (submodules)
        # Only PUBLIC modules are visible to importers of this module
        for mod_decl in getattr(module_ast, 'module_decls', []):
            if mod_decl.is_inline and mod_decl.body:
                # Determine visibility for the submodule
                submod_visibility = Visibility.PUBLIC if mod_decl.is_public else Visibility.PRIVATE
                # Recursively register the inline module in this module's namespace
                submod_path = list(mod_path) + [mod_decl.name] if mod_path else [mod_decl.name]
                mod_ns.register_module_from_ast(
                    mod_decl.name,
                    mod_decl.body,
                    submod_path,
                    visibility=submod_visibility,
                    module_map=module_map
                )

        # Register the module's own imports in its namespace, so its code can
        # resolve its import references. These imports are private: not
        # exposed to importers of this module.
        if module_map:
            for imp in getattr(module_ast, 'imports', []):
                imp_path = tuple(imp.path)
                if imp_path in module_map:
                    imp_alias = imp.alias or imp.path[-1]
                    mod_ns.register_module_from_ast(
                        imp_alias,
                        module_map[imp_path],
                        list(imp_path),
                        visibility=Visibility.PRIVATE,  # Imports are private
                        module_map=module_map
                    )

        # Create and register the module symbol.
        self.modules[alias] = ModuleSymbol(
            namespace=mod_ns,
            path=path or [],
            visibility=visibility
        )

    def method_owner(self, type_name: str):
        """The symbol that carries methods for `type_name`: a struct or an enum.
        Both have the same method tables, so every caller below is written once
        against whichever owns the name."""
        owner = self.lookup_struct(type_name)
        if owner is not None:
            return owner
        return self.lookup_enum(type_name)

    def register_method(self, struct_name: str, method_name: str, symbol: FunctionSymbol):
        """Register a method on a struct or enum, appending it to the overload
        set.

        The first registration under a name is the representative in `methods`;
        later overloads only extend `method_overloads`.
        """
        s = self.method_owner(struct_name)
        if s is not None:
            s.method_overloads.setdefault(method_name, []).append(symbol)
            if method_name not in s.methods:
                s.methods[method_name] = symbol

    # There is deliberately no spelling-keyed "overloads of method M on type T"
    # lookup here: the receiver's type name need not be bound as a simple name
    # at the call site. Ask `TypeChecker._receiver_method_overloads`, which
    # reads `method_overloads` off the resolved receiver symbol.

    def register_init_method(self, struct_name: str, symbol: FunctionSymbol):
        """Register an init method on a struct."""
        owner = self.lookup_struct(struct_name)
        if owner is not None:
            owner.init_methods.append(symbol)

    def register_specialized_method(self, struct_name: str, spec_key: Tuple[str, ...],
                                     method_name: str, method: FunctionSymbol):
        """Register a specialized method for a generic struct or enum
        instantiation.

        Args:
            struct_name: The base type name (e.g., "Vector")
            spec_key: Tuple of type argument strings (e.g., ("String",))
            method_name: The method name
            method: The FunctionSymbol for the method
        """
        owner = self.method_owner(struct_name)
        if owner:
            if spec_key not in owner.specialized_methods:
                owner.specialized_methods[spec_key] = {}
            owner.specialized_methods[spec_key][method_name] = method

    def register_conformance(self, type_name: str, trait_name: str,
                            type_assignments: Optional[Dict[str, SawType]] = None):
        """Register that a type conforms to a trait."""
        if type_name not in self.conformances:
            self.conformances[type_name] = {}
        self.conformances[type_name][trait_name] = type_assignments or {}

        # Also add to the type's own conformance list (struct or enum).
        owner = self.method_owner(type_name)
        if owner is not None:
            if trait_name not in owner.conformances:
                owner.conformances.append(trait_name)

    # =========================================================================
    # Lookup Methods
    # =========================================================================

    def lookup_function(self, name: str,
                        accessor_module: Optional[Tuple[str, ...]] = None
                        ) -> Optional[FunctionSymbol]:
        """Look up a function by name: the one declaration a bare use means.

        Routed through the overload funnel; within what it returns, the
        accessor module's own declaration wins over anything merged or imported
        under the same name. The representative in `self.functions` reflects
        only registration order, and std is merged into every namespace before
        the module registers anything, so it cannot be used for this."""
        cands = self.lookup_function_overloads(name, accessor_module)
        if not cands:
            return self.functions.get(name)
        if len(cands) > 1:
            own = (tuple(accessor_module) if accessor_module is not None
                   else self.module_path)
            for cand in cands:
                if tuple(getattr(cand, 'def_module', ()) or ()) == own:
                    return cand
        return cands[0]

    def _lookup_type(self, table: Dict[str, Any], name: str,
                     module: Optional[Tuple[str, ...]] = None):
        """Look a type up in `table` by identity or by source name.

        The identity hit comes first: everything downstream of type checking
        (codegen keys, monomorphization, mangling) holds identities, and for an
        unqualified type the two spellings coincide anyway. `module` is the
        looking module, whose own file-private names win."""
        sym = table.get(name)
        if sym is not None:
            return sym
        identity = self.resolve_type_identity(name, module)
        if identity != name:
            return table.get(identity)
        return None

    def _lookup_own_type(self, table: Dict[str, Any], name: str):
        """Look a type up in `table` by the source spelling `name`, as this
        module writes it.

        The mirror of `_lookup_type`, which is identity-first: right for
        everything downstream of type checking, wrong for an importer holding a
        spelling. std's public types are unqualified (identity = spelling), so
        identity-first would return the merged std `File` before consulting
        `type_names`, where this module's own `File` is bound, and
        `import m.{File}` would silently bind the wrong type.

        Used by the selective-import binder, whose argument is always a name
        the author wrote in braces."""
        identity = self.resolve_type_identity(name, tuple(self.module_path or ()))
        sym = table.get(identity)
        if sym is not None:
            return sym
        return table.get(name)

    def lookup_own_struct(self, name: str) -> Optional[StructSymbol]:
        """This module's own binding of the struct spelling `name`."""
        return self._lookup_own_type(self.structs, name)

    def lookup_own_enum(self, name: str) -> Optional[EnumSymbol]:
        """This module's own binding of the enum spelling `name`."""
        return self._lookup_own_type(self.enums, name)

    def lookup_own_trait(self, name: str) -> Optional[TraitSymbol]:
        """This module's own binding of the trait spelling `name`."""
        return self._lookup_own_type(self.traits, name)

    def lookup_own_type_alias(self, name: str) -> Optional[TypeAliasSymbol]:
        """This module's own binding of the type-alias spelling `name`."""
        return self._lookup_own_type(self.type_aliases, name)

    def lookup_struct(self, name: str,
                      module: Optional[Tuple[str, ...]] = None) -> Optional[StructSymbol]:
        """Look up a struct by identity or source name."""
        return self._lookup_type(self.structs, name, module)

    def lookup_enum(self, name: str,
                    module: Optional[Tuple[str, ...]] = None) -> Optional[EnumSymbol]:
        """Look up an enum by identity or source name."""
        return self._lookup_type(self.enums, name, module)

    def lookup_trait(self, name: str,
                     module: Optional[Tuple[str, ...]] = None) -> Optional[TraitSymbol]:
        """Look up a trait by identity or source name."""
        return self._lookup_type(self.traits, name, module)

    def lookup_type_alias(self, name: str,
                          module: Optional[Tuple[str, ...]] = None) -> Optional[TypeAliasSymbol]:
        """Look up a type alias by identity or source name."""
        return self._lookup_type(self.type_aliases, name, module)

    def lookup_method(self, struct_name: str, method_name: str) -> Optional[FunctionSymbol]:
        """Look up a method on a struct or enum."""
        owner = self.method_owner(struct_name)
        if owner:
            return owner.methods.get(method_name)
        return None

    def lookup_specialized_method(self, struct_name: str, spec_key: Tuple[str, ...],
                                   method_name: str) -> Optional[FunctionSymbol]:
        """Look up a specialized method for a generic struct instantiation.

        Args:
            struct_name: The base struct name (e.g., "Vector")
            spec_key: Tuple of type argument strings (e.g., ("String",))
            method_name: The method name

        Returns:
            The FunctionSymbol if found, None otherwise
        """
        owner = self.method_owner(struct_name)
        if owner and spec_key in owner.specialized_methods:
            return owner.specialized_methods[spec_key].get(method_name)
        return None

    def lookup_type(self, name: str) -> Optional[SawType]:
        """Resolve a type name to its SawType."""
        # Check type aliases first
        alias = self.lookup_type_alias(name)
        if alias is not None and alias.aliased_type:
            return alias.aliased_type
        # Check structs / enums. The built type carries the identity, not the
        # spelling, because everything downstream keys on it.
        struct = self.lookup_struct(name)
        if struct is not None:
            return SawType(kind=TypeKind.STRUCT,
                           struct_name=self._identity_of(name, struct))
        enum = self.lookup_enum(name)
        if enum is not None:
            return SawType(kind=TypeKind.ENUM,
                           enum_name=self._identity_of(name, enum))
        return None

    # =========================================================================
    # Query Methods
    # =========================================================================

    def get_return_type(self, func_name: str) -> Optional[SawType]:
        """Get the return type of a function."""
        func = self.functions.get(func_name)
        return func.return_type if func else None

    def get_method_return_type(self, struct_name: str, method_name: str) -> Optional[SawType]:
        """Get the return type of a method."""
        method = self.lookup_method(struct_name, method_name)
        return method.return_type if method else None

    def is_static_method(self, struct_name: str, method_name: str) -> bool:
        """Check if a method is static."""
        method = self.lookup_method(struct_name, method_name)
        return method.is_static if method else False

    def is_init_method(self, struct_name: str, method_name: str) -> bool:
        """Check if a method is an init method."""
        method = self.lookup_method(struct_name, method_name)
        return method.is_init if method else False

    def imported_search_sources(self):
        """`(label, namespace)` for every module an ordinary name lookup may
        fall through to.

        The one list for that question. ENTRY POINTS (here or through
        `imported_search_namespaces`): `_lookup_struct_deep` and its
        type-alias and enum twins, `trait_refines`' parent walk,
        `_cross_module_lookup`, and `_check_function_call`'s imported-function
        fallback. A selective import binds no qualifier but its
        source stays searchable, so `import m.{Child}` still finds `Child`'s
        unselected parent in `m`.

        A glob source is deliberately not here: a glob copies the names it is
        entitled to, so a name it did not copy is one this module may not see,
        and widening the walk would reach the globbed module's private
        declarations.

        The label names the module in a diagnostic; a module imported both
        ways yields twice, and callers deduplicate symbols by identity.
        """
        for qualifier, module_sym in self.modules.items():
            ns = getattr(module_sym, 'namespace', None)
            if ns is not None:
                yield (qualifier, ns)
        for label, ns in self.selective_sources:
            if ns is not None:
                yield (label, ns)

    def imported_search_namespaces(self):
        """The namespaces of `imported_search_sources`, for callers with no
        diagnostic to write.

        Spelled out rather than delegating to `imported_search_sources`,
        because this is the hottest iteration in the checker and a delegating
        generator costs two Python frames per element. Keep the two loops in
        step with `imported_search_sources`.
        """
        for module_sym in self.modules.values():
            ns = getattr(module_sym, 'namespace', None)
            if ns is not None:
                yield ns
        for _label, ns in self.selective_sources:
            if ns is not None:
                yield ns

    def coherence_search_namespaces(self):
        """Every namespace a coherence query reaches from here.

        The one place that answers "which imported modules can a conformance
        have been declared in". ENTRY POINTS:
          * `type_conforms_to`
          * `_lookup_thread_assertion`
        (the queries about what a type was declared to be, as opposed to what
        a name resolves to).

        The whole-module form lands in `modules`; the glob and selective forms
        bind no qualifier and land in `glob_sources` / `selective_sources`.
        All three are walked because the orphan rule makes a conformance
        coherent program-wide, so no import form may lose one; in particular
        `import m.*` must see a conformance `m` declares for a type declared
        elsewhere.

        Name lookups are deliberately not routed here: they are visibility
        questions, where widening the search would reach private declarations.
        """
        for module_sym in self.modules.values():
            ns = getattr(module_sym, 'namespace', None)
            if ns is not None:
                yield ns
        for _label, ns in self.glob_sources:
            if ns is not None:
                yield ns
        for _label, ns in self.selective_sources:
            if ns is not None:
                yield ns

    def type_conforms_to(self, type_name: str, trait_name: str, _visiting=None) -> bool:
        """Check if a type conforms to a trait.

        Checks this namespace, then every namespace an import reaches
        (`coherence_search_namespaces`): conformances are registered per module
        at typecheck time and only merged for codegen, so a cross-module query
        must look through imports too. The visited set guards against import
        cycles."""
        if type_name in self.conformances and trait_name in self.conformances[type_name]:
            return True
        if _visiting is None:
            _visiting = set()
        # `id()` here is a within-one-query cycle guard over Namespace objects,
        # not a persistent node identity: the set dies with the recursion and
        # must compare physical objects.
        _visiting.add(id(self))
        for ns in self.coherence_search_namespaces():
            if id(ns) not in _visiting:
                if ns.type_conforms_to(type_name, trait_name, _visiting):
                    return True
        return False

    def get_conformances(self, type_name: str) -> List[str]:
        """Get all traits a type conforms to."""
        if type_name not in self.conformances:
            return []
        return list(self.conformances[type_name].keys())

    # =========================================================================
    # The copy-tier trait name (design 219): one funnel, two forms.
    #
    # `Copy` is the name of the silently-copyable tier. Every rule that asks
    # "does this type declare that tier?" goes through here; a site that
    # asked `type_conforms_to` by a hardcoded name would silently answer "not
    # on the tier" if the name changed, and drop a retain. Anything checking
    # the copy-tier trait by name goes through one of the two accessors.
    #
    # ENTRY POINTS, by the shape the caller holds:
    #   `declares_copy_tier(name)` — the conformance lookup form (searches
    #     imported module namespaces too). Callers: `is_trivially_copyable`,
    #     `declared_copy_tier`, `type_satisfies_explicit_copy_bound`,
    #     `_payload_retainable`, and in the typechecker
    #     `_is_implicit_copy_type`, `_is_deinit_type`,
    #     `_check_implicit_copy_containment`.
    #   `names_copy_tier(conformances)` — the already-fetched form, for callers
    #     holding a `get_conformances()` list. Callers: codegen's
    #     `_get_cleanup_behavior` and `_generate_derived_copy_body`.
    # =========================================================================

    COPY_TIER_TRAIT_NAMES = frozenset({"Copy"})

    def declares_copy_tier(self, type_name: str) -> bool:
        """Whether `type_name` declares the silently-copyable tier. See the
        block comment above for the caller list."""
        return any(self.type_conforms_to(type_name, trait)
                   for trait in self.COPY_TIER_TRAIT_NAMES)

    @classmethod
    def names_copy_tier(cls, conformances) -> bool:
        """The `declares_copy_tier` question over an already-fetched conformance
        collection (`get_conformances()`), for codegen's hot paths."""
        return any(trait in conformances for trait in cls.COPY_TIER_TRAIT_NAMES)

    # =========================================================================
    # Copy-family bound satisfaction (shared by typechecker and codegen)
    #
    # These are the single source of truth for "does a concrete type satisfy a
    # `Copy`-family bound". Both the typechecker (bound-checking on calls) and
    # codegen (skipping unsatisfied bounded-extension instantiations) call them,
    # so the two phases can never disagree about whether e.g. `Vector<File>`'s
    # conditional `copy()` exists.
    # =========================================================================

    _TRIVIAL_PRIMITIVE_KINDS = frozenset({
        TypeKind.INT, TypeKind.UINT,
        TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
        TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64,
        TypeKind.FLOAT, TypeKind.BOOL,
    })

    # Primitive kinds that register an extensible pseudo-struct, so an
    # `extension Int: Fooable` conformance is keyed under this name, the same
    # key trait-method dispatch resolves a primitive receiver's methods by.
    # Every primitive is here. Derived from `ast_nodes.PRIMITIVE_EXT_KINDS`
    # (this map inverted) so the two cannot drift.
    _PRIMITIVE_CONFORMANCE_KEYS = {
        kind: name for name, kind in PRIMITIVE_EXT_KINDS.items()
    }

    def primitive_conformance_key(self, saw_type) -> Optional[str]:
        """The pseudo-struct name for a primitive type, or None if it is not one.

        Also the answer to "can this type be erased to an existential": a
        primitive is exactly the set that cannot.
        """
        if saw_type is None:
            return None
        return self._PRIMITIVE_CONFORMANCE_KEYS.get(saw_type.kind)

    # The deep-lookup walk (struct / type-alias / enum: one shape, three
    # tables). Each searches this namespace, then every namespace
    # `imported_search_namespaces` reaches, transitively.
    #
    # `_seen` is a dedup set over namespace identity, which keeps the walk
    # linear in the import graph rather than exponential in its paths (a
    # diamond, or a module imported both wholly and selectively, reaches one
    # namespace by two routes). Skipping a seen namespace is sound because the
    # walk only continues past a namespace that answered None, so a second
    # visit would answer None again. The set also terminates the walk on an
    # import cycle.

    def _lookup_struct_deep(self, name: str, _seen=None) -> Optional[StructSymbol]:
        """Look up a struct in this namespace or any imported module namespace."""
        result = self.lookup_struct(name)
        if result:
            return result
        if _seen is None:
            _seen = {id(self)}
        for ns in self.imported_search_namespaces():
            key = id(ns)
            if key in _seen:
                continue
            _seen.add(key)
            found = ns._lookup_struct_deep(name, _seen)
            if found:
                return found
        return None

    def _lookup_type_alias_deep(self, name: str, _seen=None) -> Optional[TypeAliasSymbol]:
        """Look up a type alias in this namespace or any imported module namespace."""
        result = self.lookup_type_alias(name)
        if result:
            return result
        if _seen is None:
            _seen = {id(self)}
        for ns in self.imported_search_namespaces():
            key = id(ns)
            if key in _seen:
                continue
            _seen.add(key)
            found = ns._lookup_type_alias_deep(name, _seen)
            if found:
                return found
        return None

    def is_trivially_copyable(self, saw_type: SawType) -> bool:
        """A type is trivially copyable iff it can be duplicated bitwise: all
        fields are trivially copyable, and it declares no resource trait
        (Deinit / NoCopy / Copy / ExplicitCopy). Such types auto-satisfy
        `Copy`; `.copy()` on them lowers to a bitwise copy.
        """
        if saw_type is None:
            return False
        kind = saw_type.kind
        if kind in self._TRIVIAL_PRIMITIVE_KINDS:
            return True
        if kind == TypeKind.TUPLE:
            return all(self.is_trivially_copyable(e) for e in (saw_type.element_types or []))
        if kind == TypeKind.OPTIONAL:
            return saw_type.inner_type is not None and self.is_trivially_copyable(saw_type.inner_type)
        if kind == TypeKind.ARRAY:
            # A fixed array `[T; N]` inherits T's copy class: it is trivially
            # copyable iff its element type is.
            return (saw_type.array_element_type is not None
                    and self.is_trivially_copyable(saw_type.array_element_type))
        if kind == TypeKind.STRUCT:
            name = saw_type.struct_name
            # A type alias flows to its underlying type for triviality.
            alias_sym = self._lookup_type_alias_deep(name)
            if alias_sym and alias_sym.aliased_type:
                return self.is_trivially_copyable(alias_sym.aliased_type)
            # Any declared resource trait disqualifies triviality.
            if (self.type_conforms_to(name, "Deinit") or
                self.type_conforms_to(name, "NoCopy") or
                self.declares_copy_tier(name) or
                self.type_conforms_to(name, "ExplicitCopy")):
                return False
            struct_sym = self._lookup_struct_deep(name)
            if struct_sym is None:
                # Unknown / opaque type parameter: not known to be trivial.
                return False
            # A cell field contributes its `T`; see `member_copy_tier` for why
            # the cell's own `NoCopy` stops here.
            return all(self.is_trivially_copyable(self.cell_payload(ft) or ft)
                       for ft in struct_sym.fields.values())
        if kind == TypeKind.ENUM:
            # A payload-free enum is a bare tag: it owns nothing, so a copy is
            # bitwise and there is no deinit to double-run. The gate matches
            # `is_equatable`'s auto-conformance exactly, as the spec promises
            # (the auto-Copy set and the auto-Equatable set are one set). An
            # enum carrying a payload answers False here; its tier is derived
            # structurally by `is_implicit_copy_enum`.
            name = saw_type.enum_name
            if name is None:
                return False
            if (self.type_conforms_to(name, "Deinit") or
                    self.type_conforms_to(name, "NoCopy") or
                    self.declares_copy_tier(name) or
                    self.type_conforms_to(name, "ExplicitCopy")):
                return False
            enum_sym = self._lookup_enum_deep(name)
            if enum_sym is None:
                return False
            return all(len(fields) == 0 for fields in enum_sym.variants.values())
        return False

    # The two questions the copy vocabulary answers, kept apart (design 219).
    #
    # Silently duplicable, the merged `Copy` tier: the compiler may duplicate
    # the value at a transfer with nothing written at the site. 'free' (bitwise)
    # and 'implicit' (retain) are one tier to every rule above codegen; which
    # one a type uses is an emission detail.
    #
    # Duplicable at all, the `ExplicitCopy` conformance: the value can be
    # duplicated, possibly at the cost of a spelled `.copy()`. Every silently
    # duplicable type is duplicable, so this is the wider family.
    #
    # One predicate must never answer both: an ExplicitCopy argument in a
    # silently-copying generic body would be duplicated bitwise, giving two
    # owners of one buffer.
    _SILENT_COPY_TIERS = frozenset({'free', 'implicit'})

    def is_silently_copyable(self, saw_type: SawType) -> bool:
        """Whether `saw_type` is on the merged `Copy` tier — duplicated by the
        compiler with no ceremony at the transfer site (design 219)."""
        if saw_type is None:
            return False
        return self.copy_tier(saw_type) in self._SILENT_COPY_TIERS

    def type_satisfies_copy_bound(self, saw_type: SawType) -> bool:
        """Whether a concrete type satisfies the merged `Copy` bound.

        Derived from the tier, not gated on a declaration: `Int` and an
        undeclared `struct Bag { s: String }` are both on the tier with no
        declaration owed (design 219). Escaping closures and fixed arrays get
        their tiers through `copy_tier`, so neither needs a special case.
        """
        return self.is_silently_copyable(saw_type)

    def type_satisfies_explicit_copy_bound(self, saw_type: SawType) -> bool:
        """Whether a concrete type satisfies the `ExplicitCopy` bound, the whole
        duplicable family.

        Satisfied by every silently-copyable type (copying one for free is a
        valid way to answer `copy()`, the blanket rule) and by anything
        declaring the conformance. This is the bound that licenses a spelled
        `.copy()` on an abstract `T`.
        """
        if saw_type is None:
            return False
        if self.is_silently_copyable(saw_type):
            return True
        if saw_type.kind == TypeKind.ARRAY:
            return (saw_type.array_element_type is not None
                    and self.type_satisfies_explicit_copy_bound(
                        saw_type.array_element_type))
        name = None
        if saw_type.kind == TypeKind.STRUCT:
            name = saw_type.struct_name
        elif saw_type.kind == TypeKind.ENUM:
            name = saw_type.enum_name
        elif saw_type.kind == TypeKind.STRING:
            name = "String"
        if name is None:
            return False
        return (self.type_conforms_to(name, "ExplicitCopy") or
                self.declares_copy_tier(name))

    # =========================================================================
    # The copy tier (design 139): one transfer class per type.
    #
    # Every type answers with exactly one tier, and every read consults it.
    # Ordered by how much ceremony a transfer costs, weakest first:
    #
    #   'free'      a POD bitwise copy.
    #   'implicit'  duplicated by a refcount retain at every transfer, with no
    #               ceremony from the author (String, an escaping closure, an
    #               undeclared struct with a String field).
    #   'explicit'  never duplicated implicitly: `move`, or a visible `.copy()`.
    #   'nocopy'    move-only.
    #   'abstract'  demands a bound: the written type mentions an opaque type
    #               parameter, so its class belongs to the instantiation. It
    #               joins as the strongest tier because the unknown may be
    #               move-only. Sites that decide before monomorphization (a
    #               place value read) answer from the parameter's bounds and
    #               error when they do not prove a copy; sites that emit at the
    #               instantiation substitute first and never see it.
    #
    # A wrapper is never weaker than what it wraps: an `Optional<T>`, a tuple, a
    # fixed array, and an enum's payloads all join their parts' tiers. Without
    # the join, a whole-optional read of a move-only payload would be a bitwise
    # alias that double-drops.
    #
    # A declared conformance wins over the structural join, so a user type's
    # policy is its author's choice. Registration refuses a bare enum whose
    # join is 'explicit' or 'nocopy', so a declaration is always present where
    # one is owed.
    # =========================================================================

    _COPY_TIER_ORDER = ('free', 'implicit', 'explicit', 'nocopy', 'abstract')

    # Names that reach the type predicates as a struct-kinded SawType even
    # though they are compiler-known types, not type parameters. The parser
    # defaults an unknown capitalized name to STRUCT, so the "resolves to no
    # declaration" test that identifies a type parameter needs them excluded.
    _BUILTIN_TYPE_NAMES = frozenset({
        "String", "Int", "UInt", "Float", "Bool", "Void", "Never", "Self",
        "Int8", "Int16", "Int32", "Int64",
        "UInt8", "UInt16", "UInt32", "UInt64",
    })

    def _tier_join(self, a: str, b: str) -> str:
        """The stronger of two tiers — a composite is never weaker than a part."""
        order = self._COPY_TIER_ORDER
        return a if order.index(a) >= order.index(b) else b

    def is_abstract_type_name(self, name: str) -> bool:
        """True when `name` is an opaque type parameter rather than a declared
        type. A type parameter reaches here as a struct-kinded SawType carrying
        its own name (`SawType.substitute` keys off exactly that), so the test
        is whether the name resolves to any declaration at all — the same
        "opaque / unresolved type parameter" reading `_send_sync` uses."""
        if name is None or name in self._BUILTIN_TYPE_NAMES:
            return False
        return (self._lookup_struct_deep(name) is None
                and self._lookup_enum_deep(name) is None
                and self._lookup_type_alias_deep(name) is None)

    def _has_abstract_type_arg(self, saw_type: SawType, _visiting=None) -> bool:
        """Does any type argument of this instantiation mention a parameter?

        `_visiting` must be threaded through, as everywhere under `copy_tier`:
        a cyclic type through a user generic (`enum E { case K(p: Pair<E>) }`)
        re-enters `copy_tier(E)` here, and a fresh visiting set would recurse
        without bound.
        """
        return any(self.copy_tier(arg, _visiting) == 'abstract'
                   for arg in (saw_type.type_args or [])
                   if arg is not None)

    # The interior-mutability cell (design 186). Named once, here, because two
    # questions have to agree about it: what a cell is, and what a cell field
    # contributes to the type holding one.
    INTERIOR_CELL_NAME = "UnsafeMutableInterior"

    def cell_payload(self, saw_type: SawType) -> Optional[SawType]:
        """`T` when `saw_type` is an `UnsafeMutableInterior<T>`, else None."""
        if saw_type is None or saw_type.kind != TypeKind.STRUCT:
            return None
        name = saw_type.struct_name
        if name is None:
            return None
        if declaration_base(name) != self.INTERIOR_CELL_NAME:
            return None
        args = saw_type.type_args or []
        return args[0] if args else None

    def is_cell_carrying(self, saw_type: SawType, _visiting=None) -> bool:
        """Does `saw_type` transitively contain an interior cell (design 186)?

        Rust's `Freeze` analysis, inverted. A value of such a type may be
        mutated through a shared borrow, so:
          * a receiver or borrow of one always travels by pointer, so `&self`
            reaches the caller's storage (`_self_by_pointer_for`);
          * a `static` of one never lands in a read-only segment;
          * codegen assumes nothing immutable behind a shared borrow of one;
          * structural `Sync` derivation is blocked (sharing needs `UnsafeSync`).
        `Send` is unaffected: a cell moves fine.

        The walk covers every place a cell's storage can be inline (struct
        fields, enum payloads, tuples, optionals, fixed arrays) and stops at an
        indirection: a `Box<Cell>` holds a pointer, not the cell's bytes.
        """
        if saw_type is None:
            return False
        if _visiting is None:
            _visiting = frozenset()
        kind = saw_type.kind
        if kind == TypeKind.ARRAY:
            return self.is_cell_carrying(saw_type.array_element_type, _visiting)
        if kind == TypeKind.OPTIONAL:
            return self.is_cell_carrying(saw_type.inner_type, _visiting)
        if kind == TypeKind.TUPLE:
            return any(self.is_cell_carrying(e, _visiting)
                       for e in (saw_type.element_types or []))
        if kind == TypeKind.STRUCT:
            name = saw_type.struct_name
            if name is None:
                return False
            if self.cell_payload(saw_type) is not None:
                return True
            base = declaration_base(name)
            alias_sym = self._lookup_type_alias_deep(base)
            if alias_sym and alias_sym.aliased_type:
                return self.is_cell_carrying(alias_sym.aliased_type, _visiting)
            if name in _visiting:
                return False
            _visiting = _visiting | {name}
            sym = self._lookup_struct_deep(name) or self._lookup_struct_deep(base)
            if sym is None:
                enum_sym = self._lookup_enum_deep(name) or self._lookup_enum_deep(base)
                if enum_sym is not None:
                    return self._enum_is_cell_carrying(enum_sym, saw_type, _visiting)
                return False
            type_map = self._struct_type_arg_map(sym, saw_type)
            for field_type in (sym.fields or {}).values():
                if field_type is None:
                    continue
                if type_map:
                    field_type = field_type.substitute(type_map)
                if self.is_cell_carrying(field_type, _visiting):
                    return True
            return False
        if kind == TypeKind.ENUM:
            name = saw_type.enum_name
            if name is None or name in _visiting:
                return False
            enum_sym = self._lookup_enum_deep(name)
            if enum_sym is None:
                return False
            return self._enum_is_cell_carrying(enum_sym, saw_type,
                                               _visiting | {name})
        return False

    def _enum_is_cell_carrying(self, enum_sym, saw_type: SawType,
                               _visiting) -> bool:
        """A cell inline in any payload makes the whole enum cell-carrying."""
        type_map = self._enum_type_arg_map(enum_sym, saw_type)
        for payload in enum_sym.variants.values():
            for _fname, ptype in payload:
                if ptype is None:
                    continue
                if type_map:
                    ptype = ptype.substitute(type_map)
                if self.is_cell_carrying(ptype, _visiting):
                    return True
        return False

    def struct_is_cell_carrying(self, struct_name: str) -> bool:
        """`is_cell_carrying` asked of a struct by name.

        The receiver-ABI decision is made at method declaration time, where the
        name — possibly a monomorphized `SpinLock$1$Int` — is what is in hand. A
        monomorphized name whose fields are not registered falls back to its
        template, which is the right answer whenever the cell is declared in the
        template itself: every `SpinLock<T>` has one wherever `SpinLock` does.
        """
        if not struct_name:
            return False
        cached = self._cell_carrying_by_name.get(struct_name)
        if cached is not None:
            return cached
        result = self.is_cell_carrying(
            SawType(TypeKind.STRUCT, struct_name=struct_name))
        base = declaration_base(struct_name)
        if not result and base != struct_name:
            result = self.is_cell_carrying(
                SawType(TypeKind.STRUCT, struct_name=base))
        self._cell_carrying_by_name[struct_name] = result
        return result

    def member_copy_tier(self, saw_type: SawType, _visiting=None) -> str:
        """The copy tier a member of `saw_type` contributes to its container.

        Identical to `copy_tier` except on the interior-mutability cell, which
        is `NoCopy` as a value (a copied cell is a second cell, so
        `let c = self.inner` is refused) while a cell field contributes its
        `T`'s class. The container states its own policy visibly:
        `SpinLock<T>`, `Once<T>` and `Atomic<T>` declare `NoCopy`.

        The clause fires on the cell itself only, so a declared policy on the
        holding type still wins (`copy_tier` consults `declared_copy_tier`
        first): `Atomic<Int>` is `nocopy`, while an undeclared
        `struct C { cell: UnsafeMutableInterior<Int> }` is `free`. Pinned by
        `examples/atomic_nocopy_cell_clause.saw`.
        """
        payload = self.cell_payload(saw_type)
        if payload is not None:
            return self.copy_tier(payload, _visiting)
        return self.copy_tier(saw_type, _visiting)

    def declared_copy_tier(self, type_name: str) -> str:
        """The tier a type name declares, or 'free' when it declares none.

        The order is the rule. A type may declare both `Copy` and
        `ExplicitCopy`, and `Copy` wins: it says what a transfer costs, while
        `ExplicitCopy` says only that a copy exists, which is true of every
        silently-copyable type anyway.

        `NoCopy` outranks both: it is the deliberate opt-out, stricter than
        what the members would derive.
        """
        if self.type_conforms_to(type_name, "NoCopy"):
            return 'nocopy'
        if self.declares_copy_tier(type_name):
            return 'implicit'
        if self.type_conforms_to(type_name, "ExplicitCopy"):
            return 'explicit'
        return 'free'

    def copy_tier(self, saw_type: SawType, _visiting=None) -> str:
        """The single transfer class of `saw_type` (design 139)."""
        if saw_type is None:
            return 'free'
        saw_type = self._normalize_struct_enum(saw_type)
        kind = saw_type.kind
        if kind == TypeKind.FUNCTION:
            # An escaping closure carries a refcounted heap env and copies by
            # retaining it; a non-escaping one borrows and owns nothing.
            return 'implicit' if getattr(saw_type, 'func_is_escaping', False) else 'free'
        if kind == TypeKind.STRING:
            return 'implicit'
        if kind in self._TRIVIAL_PRIMITIVE_KINDS:
            return 'free'
        if kind == TypeKind.ARRAY:
            return self.copy_tier(saw_type.array_element_type, _visiting)
        if kind == TypeKind.OPTIONAL:
            return self.copy_tier(saw_type.inner_type, _visiting)
        if kind == TypeKind.TUPLE:
            tier = 'free'
            for element in saw_type.element_types or []:
                tier = self._tier_join(tier, self.copy_tier(element, _visiting))
            return tier
        if kind == TypeKind.STRUCT:
            name = saw_type.struct_name
            if name is None:
                return 'free'
            alias_sym = self._lookup_type_alias_deep(name)
            if alias_sym and alias_sym.aliased_type:
                return self.copy_tier(alias_sym.aliased_type, _visiting)
            declared = self.declared_copy_tier(name)
            if declared != 'free':
                # A declared policy is instantiation-uniform by construction:
                # `Vector<T>` is ExplicitCopy for every `T`. Nothing abstract
                # about the arguments can weaken or strengthen it.
                return declared
            if self.is_abstract_type_name(name):
                return 'abstract'
            if self._has_abstract_type_arg(saw_type, _visiting):
                # An undeclared struct's tier is a structural answer, and a
                # structural answer over abstract arguments is not knowable from
                # the written type.
                return 'abstract'
            return self._struct_structural_copy_tier(saw_type, _visiting)
        if kind == TypeKind.ENUM:
            name = saw_type.enum_name
            if name is None:
                return 'free'
            declared = self.declared_copy_tier(name)
            if declared != 'free':
                return declared
            return self._enum_structural_copy_tier(saw_type, _visiting)
        return 'free'

    def _struct_structural_copy_tier(self, saw_type: SawType, _visiting=None) -> str:
        """The join of an undeclared struct's field tiers.

        The counterpart of `_enum_structural_copy_tier`. A struct whose owning
        members are all trivial or Copy needs no declared policy, but its tier
        must still be the join: an undeclared `struct P { name: String }` is
        'implicit', and must agree with `_needs_cleanup`'s per-binding drop or
        one allocation gets N releases. A declared policy wins (checked before
        this runs).
        """
        name = saw_type.struct_name
        if _visiting is None:
            _visiting = frozenset()
        if name in _visiting:
            # A struct reaching itself through a field. The back-edge adds no
            # tier of its own: whatever closes the cycle is behind a Box or an
            # Optional, each of which contributes its own tier at that field.
            return 'free'
        _visiting = _visiting | {name}
        sym = self._lookup_struct_deep(name)
        if sym is None:
            return 'free'
        type_map = self._struct_type_arg_map(sym, saw_type)
        tier = 'free'
        for field_type in (sym.fields or {}).values():
            if field_type is None:
                continue
            if type_map:
                field_type = field_type.substitute(type_map)
            tier = self._tier_join(
                tier, self.member_copy_tier(field_type, _visiting))
        return tier

    def _struct_type_arg_map(self, sym, saw_type: SawType):
        """Map a struct's type-parameter names to an instantiation's arguments."""
        params = getattr(sym, 'type_params', None) or []
        args = saw_type.type_args or []
        if not params or not args:
            return {}
        return {p.name: a for p, a in zip(params, args) if a is not None}

    # The read policy: the one mapping from a copy tier to what a value read
    # out of storage somebody else owns costs. ENTRY POINTS:
    #
    #   * typechecker `_payload_read_policy` / `_check_payload_read` — the
    #     optional-payload reads (`o!`, `??`'s left operand, an
    #     `if let`/`guard let` binding);
    #   * typechecker `_check_match_expr` — a match scrutinee;
    #   * `place_uses._value_read_ok` / `_value_read_would_refuse` — the point
    #     a `borrows` place becomes a value;
    #   * `coro_transform._frame_read_policy` — a frame-slot read;
    #   * `codegen/match.py` `_generate_match_expr` — which enums a match
    #     consumes and which it borrows-with-retain.
    #
    # Every site must ask here: separately derived answers disagree, and one
    # such disagreement freed a Copy enum's payload at the first match arm's
    # end.
    _READ_POLICY_BY_TIER = {
        'free': 'trivial',
        'implicit': 'retain',
        # The ExplicitCopy tier reads as move-only: nothing here may duplicate
        # the value unwritten. What separates the two is only what the
        # diagnostic can offer (`.copy()` exists or not), asked at the refusal
        # rather than carried as a second policy.
        'explicit': 'nocopy',
        'nocopy': 'nocopy',
        # An opaque type parameter's tier is decided per instantiation. Sites
        # that emit code substitute first and never see this; sites that must
        # answer now use a bitwise read rather than guess a retain that a
        # `Vector` instantiation would turn into a silent deep copy.
        'abstract': 'trivial',
    }

    def read_policy(self, saw_type: SawType) -> str:
        """What a value read of `saw_type` out of storage its owner keeps costs:
        'trivial' (bitwise), 'retain' or 'nocopy'.

        The one derivation from the copy tiers; see `_READ_POLICY_BY_TIER`
        above for the entry points that ask it."""
        return self._READ_POLICY_BY_TIER.get(self.copy_tier(saw_type), 'trivial')

    def is_structurally_implicit_copy(self, saw_type: SawType, _visiting=None) -> bool:
        """Is this composite Copy without declaring it?

        True for an undeclared struct or enum whose owning members are all
        trivial or Copy: the automatic tier, where no declaration is needed and
        none may be demanded. Copying such a value retains each refcounted
        member (`_generate_copy`'s recursive retain for any cleanup-owning
        aggregate).
        """
        return self.copy_tier(saw_type, _visiting) == 'implicit'

    def _enum_structural_copy_tier(self, saw_type: SawType, _visiting=None) -> str:
        """The join of an enum's payload tiers, type arguments substituted in.

        This is what gives the compiler-owned wrappers their tier without a
        declaration to read: `Result`'s variants carry the opaque parameters
        `T`/`E`, so the payload types must be instantiated before they can be
        classified at all. A user enum reaches here only when it declares no
        policy, which registration permits exactly when this join is 'free' or
        'implicit'.
        """
        name = saw_type.enum_name
        if _visiting is None:
            _visiting = frozenset()
        if name in _visiting:
            # An enum reaching itself through a payload. The back-edge adds no
            # tier of its own: whatever closes the cycle is behind a Box or an
            # Optional, each of which contributes its own tier at that field.
            return 'free'
        _visiting = _visiting | {name}
        sym = self._lookup_enum_deep(name)
        if sym is None:
            return 'free'
        type_map = self._enum_type_arg_map(sym, saw_type)
        tier = 'free'
        for variant_fields in sym.variants.values():
            for _fname, field_type in variant_fields:
                if field_type is None:
                    continue
                if type_map:
                    field_type = field_type.substitute(type_map)
                tier = self._tier_join(
                    tier, self.member_copy_tier(field_type, _visiting))
        return tier

    def _enum_type_arg_map(self, sym, saw_type: SawType):
        """Map an enum's type-parameter names to an instantiation's arguments."""
        params = getattr(sym, 'type_params', None) or []
        args = saw_type.type_args or []
        if not params or not args:
            return {}
        return {p.name: a for p, a in zip(params, args) if a is not None}

    def is_implicit_copy_enum(self, saw_type: SawType, _visiting=None) -> bool:
        """Structural Copy classification for enums.

        True iff the enum carries at least one owning Copy payload (`String`,
        `Arc`) and every payload is cleanly retainable (POD or itself Copy).
        Such an enum copies by retaining its active payload, like a Copy
        struct; treating it as bitwise would release the shared payload once
        per copy. An ExplicitCopy/NoCopy payload (`Vector`, `File`,
        `Box<any …>`) makes this False: that enum is move-only.

        A generic enum's payload types must be substituted before they can be
        classified: `Slot<K>`'s payload is the opaque `K`, `Slot<Res>`'s a
        real type with a real tier.
        """
        saw_type = self._normalize_struct_enum(saw_type)
        if saw_type is None or saw_type.kind != TypeKind.ENUM:
            return False
        name = saw_type.enum_name
        if name is None:
            return False
        if _visiting is None:
            _visiting = set()
        if name in _visiting:
            # Recursion guard (an enum reaching itself through a payload): treat
            # the back-edge as retainable-but-non-owning so it neither loops nor
            # forces the whole enum non-retainable.
            return False
        _visiting = _visiting | {name}
        # A declared move-only conformance disqualifies implicit copying.
        if (self.type_conforms_to(name, "NoCopy")
                or self.type_conforms_to(name, "ExplicitCopy")):
            return False
        sym = self._lookup_enum_deep(name)
        if sym is None:
            return False
        type_map = self._enum_type_arg_map(sym, saw_type)
        has_owning = False
        for variant_fields in sym.variants.values():
            for _fname, ftype in variant_fields:
                if type_map and ftype is not None:
                    ftype = ftype.substitute(type_map)
                ok, owning = self._payload_retainable(ftype, _visiting)
                if not ok:
                    return False
                has_owning = has_owning or owning
        return has_owning

    def _payload_retainable(self, t: SawType, _visiting):
        """Classify an enum-payload field type for structural Copy.

        Returns (retainable, owning): `retainable` is True when a copy of the enum
        can duplicate this field by a bitwise copy (POD) or a refcount retain
        (Copy); `owning` is True only for a refcounted (Copy) field
        — the presence of at least one is what makes the enclosing enum
        Copy rather than trivially copyable.
        """
        if t is None:
            return (False, False)
        if self.is_trivially_copyable(t):
            return (True, False)
        k = t.kind
        if k == TypeKind.STRING:
            return (True, True)
        if k == TypeKind.OPTIONAL:
            return self._payload_retainable(t.inner_type, _visiting)
        if k == TypeKind.ARRAY:
            return self._payload_retainable(t.array_element_type, _visiting)
        if k == TypeKind.STRUCT:
            n = t.struct_name
            if n is not None and self.declares_copy_tier(n):
                return (True, True)
            # ExplicitCopy / NoCopy / Deinit struct: not cleanly retainable.
            return (False, False)
        if k == TypeKind.ENUM:
            if self.is_implicit_copy_enum(t, _visiting):
                return (True, True)
            # A payload-free / all-POD nested enum is bitwise-retainable (non-owning);
            # anything else (owning ExplicitCopy/NoCopy payload) is not.
            sym = self._lookup_enum_deep(t.enum_name) if t.enum_name else None
            if sym is not None:
                nested_map = self._enum_type_arg_map(sym, t)
                if all(self.is_trivially_copyable(
                            ft.substitute(nested_map) if nested_map and ft is not None
                            else ft)
                        for vf in sym.variants.values() for _n, ft in vf):
                    return (True, False)
            return (False, False)
        return (False, False)

    def _normalize_struct_enum(self, saw_type: SawType) -> SawType:
        """A type annotation like `-> Ordering` can reach the trait predicates as
        a struct-kinded SawType (the parser defaults an unknown capitalized name
        to STRUCT, and not every path runs it through `_resolve_type`). If the
        name is actually a registered enum (and neither a struct nor an alias),
        rewrite it to an ENUM SawType so the enum branches fire."""
        if (saw_type is not None and saw_type.kind == TypeKind.STRUCT
                and saw_type.struct_name is not None
                and self._lookup_struct_deep(saw_type.struct_name) is None
                and self._lookup_type_alias_deep(saw_type.struct_name) is None
                and self._lookup_enum_deep(saw_type.struct_name) is not None):
            return SawType(TypeKind.ENUM, enum_name=saw_type.struct_name,
                           type_args=saw_type.type_args)
        return saw_type

    def is_equatable(self, saw_type: SawType) -> bool:
        saw_type = self._normalize_struct_enum(saw_type)
        """Whether values of `saw_type` may be compared with `==`/`!=` (design 32).

        Mirrors the Copy family's house rule:
          - primitives (integers, Bool, Float) and String conform builtin;
          - trivial (POD) structs and payload-free enums auto-conform (the exact
            auto-Copy set), so every field / payload is itself Equatable;
          - any struct or enum with a declared `extension T: Equatable {}` (or a
            hand-written `equals`) conforms;
          - tuples conform iff every element does (design 32 item 8).
        Resource types never satisfy this: they are neither trivially copyable
        nor accepted as Equatable conformers.
        """
        if saw_type is None:
            return False
        kind = saw_type.kind
        if kind in self._TRIVIAL_PRIMITIVE_KINDS:
            return True
        if kind == TypeKind.STRING:
            return True
        if kind == TypeKind.TUPLE:
            return all(self.is_equatable(e) for e in (saw_type.element_types or []))
        if kind == TypeKind.OPTIONAL:
            # `T?` is Equatable iff `T` is: None==None true, None vs Some
            # false, payload-deep otherwise.
            return saw_type.inner_type is not None and self.is_equatable(saw_type.inner_type)
        if kind == TypeKind.ARRAY:
            # `[T; N]` is Equatable iff its element type is, compared element
            # by element.
            return (saw_type.array_element_type is not None
                    and self.is_equatable(saw_type.array_element_type))
        if kind == TypeKind.STRUCT:
            name = saw_type.struct_name
            alias_sym = self._lookup_type_alias_deep(name)
            if alias_sym and alias_sym.aliased_type:
                return self.is_equatable(alias_sym.aliased_type)
            # Declared conformance (empty-body synthesis or a custom equals).
            if self.type_conforms_to(name, "Equatable"):
                return True
            # Auto-conform: the trivially-copyable (POD) set, exactly as
            # auto-Copy, further restricted to members the derive can actually
            # lower. is_trivially_copyable already excludes String / resource
            # fields; the field-wise is_equatable pass additionally excludes
            # optional / array members, which are not comparable yet.
            if not self.is_trivially_copyable(saw_type):
                return False
            struct_sym = self._lookup_struct_deep(name)
            if struct_sym is None:
                return False
            return all(self.is_equatable(ft) for ft in struct_sym.fields.values())
        if kind == TypeKind.ENUM:
            name = saw_type.enum_name
            if self.type_conforms_to(name, "Equatable"):
                return True
            # Auto-conform: payload-free enums keep their tag-only ==.
            enum_sym = self._lookup_enum_deep(name)
            if enum_sym is None:
                return False
            return all(len(fields) == 0 for fields in enum_sym.variants.values())
        return False

    _ORDERED_PRIMITIVE_KINDS = frozenset({
        TypeKind.INT, TypeKind.UINT,
        TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
        TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64,
        TypeKind.FLOAT,
    })

    def is_comparable(self, saw_type: SawType) -> bool:
        """Whether values of `saw_type` may be ordered with `< <= > >=`.

        Integer types, Float, and String conform builtin. There is no auto-
        conformance for user types (field order is a semantic choice), so a
        struct/enum is Comparable only when it declares `extension T: Comparable`
        (empty-body synthesis or a hand-written `compare`). A type alias flows to
        its underlying type. Bool and other kinds are not ordered.
        """
        saw_type = self._normalize_struct_enum(saw_type)
        if saw_type is None:
            return False
        kind = saw_type.kind
        if kind in self._ORDERED_PRIMITIVE_KINDS:
            return True
        if kind == TypeKind.STRING:
            return True
        if kind == TypeKind.STRUCT:
            name = saw_type.struct_name
            alias_sym = self._lookup_type_alias_deep(name)
            if alias_sym and alias_sym.aliased_type:
                return self.is_comparable(alias_sym.aliased_type)
            return self.type_conforms_to(name, "Comparable")
        if kind == TypeKind.ENUM:
            return self.type_conforms_to(saw_type.enum_name, "Comparable")
        return False

    def is_hashable(self, saw_type: SawType) -> bool:
        """Whether values of `saw_type` may be used as a hash-map key.

        Mirrors `is_equatable`'s gating exactly (the hash/== contract rides on
        Equatable): primitives and String conform builtin; trivial (POD) structs
        and payload-free enums auto-conform; anything else opts in with
        `extension T: Hashable {}`; optionals/arrays/tuples are Hashable iff their
        elements are.
        """
        saw_type = self._normalize_struct_enum(saw_type)
        if saw_type is None:
            return False
        kind = saw_type.kind
        if kind in self._TRIVIAL_PRIMITIVE_KINDS:
            return True
        if kind == TypeKind.STRING:
            return True
        if kind == TypeKind.TUPLE:
            return all(self.is_hashable(e) for e in (saw_type.element_types or []))
        if kind == TypeKind.OPTIONAL:
            return saw_type.inner_type is not None and self.is_hashable(saw_type.inner_type)
        if kind == TypeKind.ARRAY:
            return (saw_type.array_element_type is not None
                    and self.is_hashable(saw_type.array_element_type))
        if kind == TypeKind.STRUCT:
            name = saw_type.struct_name
            alias_sym = self._lookup_type_alias_deep(name)
            if alias_sym and alias_sym.aliased_type:
                return self.is_hashable(alias_sym.aliased_type)
            if self.type_conforms_to(name, "Hashable"):
                return True
            if not self.is_trivially_copyable(saw_type):
                return False
            struct_sym = self._lookup_struct_deep(name)
            if struct_sym is None:
                return False
            return all(self.is_hashable(ft) for ft in struct_sym.fields.values())
        if kind == TypeKind.ENUM:
            name = saw_type.enum_name
            if self.type_conforms_to(name, "Hashable"):
                return True
            enum_sym = self._lookup_enum_deep(name)
            if enum_sym is None:
                return False
            return all(len(fields) == 0 for fields in enum_sym.variants.values())
        return False

    _PRINTABLE_PRIMITIVE_KINDS = frozenset({
        TypeKind.INT, TypeKind.UINT,
        TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
        TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64,
        TypeKind.FLOAT, TypeKind.BOOL,
    })

    def trait_refines(self, trait_name: str, target: str) -> bool:
        """Whether `trait_name` is `target` or transitively refines it via parent
        traits (e.g. `Error` refines `Printable`)."""
        seen = set()
        stack = [trait_name]
        while stack:
            name = stack.pop()
            if name == target:
                return True
            if name in seen:
                continue
            seen.add(name)
            info = self.lookup_trait(name)
            if info is None:
                for ns in self.imported_search_namespaces():
                    found = ns.lookup_trait(name)
                    if found is not None:
                        info = found
                        break
            if info is not None:
                stack.extend(getattr(info, 'parent_traits', []) or [])
        return False

    def _erased_trait_of(self, saw_type: SawType) -> Optional[str]:
        """The trait name if `saw_type` is an erased value (`any T`, `&any T`, or
        `Box<any T, A>`); else None (mirrors codegen's receiver detection)."""
        if saw_type is None:
            return None
        if saw_type.kind == TypeKind.EXISTENTIAL:
            return saw_type.existential_trait
        if (saw_type.kind == TypeKind.REFERENCE and saw_type.inner_type is not None
                and saw_type.inner_type.kind == TypeKind.EXISTENTIAL):
            return saw_type.inner_type.existential_trait
        if (saw_type.kind == TypeKind.STRUCT and saw_type.struct_name == "Box"
                and saw_type.type_args
                and saw_type.type_args[0].kind == TypeKind.EXISTENTIAL):
            return saw_type.type_args[0].existential_trait
        return None

    def is_printable(self, saw_type: SawType) -> bool:
        """Whether values of `saw_type` are Printable.

        Int/UInt + the fixed-width integer types, Float, Bool, and String conform
        builtin (the compiler renders them inline). There is no auto-conformance
        for user types: a struct/enum is Printable only when it declares
        `extension T: Printable` (or `extension T: Error`, which refines it) or a
        hand-written conformance. A type alias flows to its underlying type.
        """
        # An erased value (`any T` / `&any T` / `Box<any T, A>`) is Printable
        # when its trait is Printable or refines it (Error); `to_string`/`format`
        # dispatch through the vtable.
        erased_trait = self._erased_trait_of(saw_type)
        if erased_trait is not None:
            return self.trait_refines(erased_trait, "Printable")
        saw_type = self._normalize_struct_enum(saw_type)
        if saw_type is None:
            return False
        kind = saw_type.kind
        if kind in self._PRINTABLE_PRIMITIVE_KINDS:
            return True
        if kind == TypeKind.STRING:
            return True
        if kind == TypeKind.STRUCT:
            name = saw_type.struct_name
            alias_sym = self._lookup_type_alias_deep(name)
            if alias_sym and alias_sym.aliased_type:
                return self.is_printable(alias_sym.aliased_type)
            return (self.type_conforms_to(name, "Printable")
                    or self.type_conforms_to(name, "Error"))
        if kind == TypeKind.ENUM:
            name = saw_type.enum_name
            return (self.type_conforms_to(name, "Printable")
                    or self.type_conforms_to(name, "Error"))
        return False

    def type_satisfies_bound(self, saw_type: SawType, bound: str) -> bool:
        """Whether a concrete type satisfies a single type-parameter bound.

        `Copy` is tier-derived: the merged silently-copyable tier and nothing
        else, so a type that copies with ceremony does not satisfy it.
        `ExplicitCopy` is the wider duplicable family (every Copy type, plus
        the declared conformers). `Send`/`Sync` are structural marker traits;
        `Equatable` is structural too (auto-Copy set + declared conformers);
        every other trait bound is an ordinary conformance lookup.
        """
        if bound == "Copy":
            return self.type_satisfies_copy_bound(saw_type)
        if bound == "ExplicitCopy":
            return self.type_satisfies_explicit_copy_bound(saw_type)
        if bound == "Equatable":
            return self.is_equatable(saw_type)
        if bound == "Comparable":
            return self.is_comparable(saw_type)
        if bound == "Hashable":
            return self.is_hashable(saw_type)
        if bound == "Printable":
            return self.is_printable(saw_type)
        if bound == "Send":
            return self.is_send(saw_type)
        if bound == "Sync":
            return self.is_sync(saw_type)
        name = None
        if saw_type is None:
            return False
        if saw_type.kind == TypeKind.STRUCT:
            name = saw_type.struct_name
        elif saw_type.kind == TypeKind.ENUM:
            name = saw_type.enum_name
        elif saw_type.kind == TypeKind.STRING:
            name = "String"
        else:
            # A primitive conforms to a user trait through the same
            # conformance key trait-method dispatch uses for its pseudo-struct
            # (`extension Int: Fooable`).
            name = self._PRIMITIVE_CONFORMANCE_KEYS.get(saw_type.kind)
        if name is None:
            return False
        return self.type_conforms_to(name, bound)

    # =========================================================================
    # Send / Sync structural derivation
    #
    # Compiler-known marker traits, auto-derived structurally (the auto-Copy
    # pattern); `extension X: Send` is not accepted. These two methods are the
    # single source of truth for "is this concrete type Send / Sync", shared
    # by the typechecker's bound checks and the spawn capture audit.
    #
    #   - Primitives, Bool, Float: Send + Sync.
    #   - String: Send + Sync (immutable buffer, atomic refcount).
    #   - UnsafePointer<T>: neither (poisons its containers structurally).
    #   - Struct/enum: Send iff every field/payload is Send; Sync likewise.
    #   - A declared `UnsafeSend`/`UnsafeSync` conformance (with conditional
    #     bounds re-checked per instantiation) answers before the structural
    #     walk; that is how `Arc`, `Mutex`, `Channel` and the other wrappers
    #     over raw pointers become thread-safe (design 186).
    # =========================================================================

    def is_send(self, saw_type: SawType) -> bool:
        return self._send_sync(saw_type, want_sync=False, visiting=set())

    def is_sync(self, saw_type: SawType) -> bool:
        return self._send_sync(saw_type, want_sync=True, visiting=set())

    # The thread-crossing positions. Every value that crosses from one thread
    # to another does so at one of these, and each asks `send_check` rather
    # than pairing `is_send` with a `thread_safety_note` of its own, so no
    # position can lose the note.
    #
    #   spawn capture   `Thread.spawn { … }`'s captured values     [typechecker]
    #   spawn result    `Thread.spawn { … }`'s result, via join    [typechecker]
    #   task frame parameter   a `TaskGroup(threads:)` root's params  [transform]
    #   task frame local       … its across-suspension locals         [transform]
    #   task frame result      … its result, via join                 [transform]
    SEND_POSITIONS = (
        "spawn capture", "spawn result",
        "task frame parameter", "task frame local", "task frame result",
    )

    def send_check(self, saw_type: SawType, position: str, assume=None):
        """None when `saw_type` may cross a thread boundary at `position`;
        otherwise the explanatory note to append to the caller's message.

        The caller owns the sentence naming what it is refusing (a capture, a
        parameter, a result) and its own reporting idiom — the typechecker
        reports, the coroutine transform raises. This owns the question, the
        thread-safety note that must ride with every refusal, and the list of
        positions above.

        `assume` is the enclosing generic's declared bounds, as the
        `(send_names, sync_names)` pair `_assumed` reads. The structural walk
        answers False for an abstract `T`, which is right at a concrete
        boundary but wrong inside a generic body, where `<T: Send>` is the
        caller's promise. Passing it asks "is this Send given what the
        signature declares".
        """
        assert position in self.SEND_POSITIONS, position
        if self._send_sync(saw_type, want_sync=False, visiting=set(),
                           assume=assume):
            return None
        return self.thread_safety_note(saw_type, False, assume)

    # ------------------------------------------------------------- design 186
    # The declared assertions, and the derivation they stand in for.

    ASSERTION_FOR = {False: "UnsafeSend", True: "UnsafeSync"}

    def _lookup_thread_assertion(self, type_name: str, trait_name: str,
                                 _visiting=None):
        """The bound lists a declared `UnsafeSend`/`UnsafeSync` carries, or None.

        Looks through imported namespaces exactly as `type_conforms_to` does,
        and through the same funnel (`coherence_search_namespaces`): a
        conformance is registered in the module that declares it and the tables
        are only merged for codegen, so the query has to walk every import
        form, a glob included.
        """
        table = self.thread_assertions.get(type_name)
        if table is not None and trait_name in table:
            return table[trait_name]
        if _visiting is None:
            _visiting = set()
        _visiting.add(id(self))
        for ns in self.coherence_search_namespaces():
            if id(ns) not in _visiting:
                found = ns._lookup_thread_assertion(type_name, trait_name,
                                                    _visiting)
                if found is not None:
                    return found
        return None

    def _assertion_applies(self, name: str, saw_type: SawType,
                           want_sync: bool, assume, visiting=None) -> bool:
        """Does `name`'s declared assertion hold for this instantiation?

        A conditional header (`extension Vector<T: Send, A: Send>: UnsafeSend`)
        is a promise about the instantiations that satisfy its bounds and about
        no others, so the bounds are re-checked here against the type arguments
        rather than taken once at the declaration.
        """
        bounds = self._lookup_thread_assertion(declaration_base(name),
                                               self.ASSERTION_FOR[want_sync])
        if bounds is None:
            return False
        args = list(saw_type.type_args or [])
        if len(args) < len(bounds):
            # A trailing argument left to its default: `Vector<Int>` writes one
            # argument and means two. The promise is about the type the
            # reference denotes, so the bound is checked against the default.
            base = declaration_base(name)
            sym = self._lookup_struct_deep(base) or self._lookup_enum_deep(base)
            params = list(getattr(sym, 'type_params', None) or []) if sym else []
            while len(args) < len(bounds) and len(args) < len(params):
                args.append(getattr(params[len(args)], 'default', None))
        for index, param_bounds in enumerate(bounds):
            if not param_bounds:
                continue
            if index >= len(args) or args[index] is None:
                # An un-parameterized spelling with no default to fall back on:
                # nothing to check the bound against, so the conditional promise
                # is not made.
                return False
            for bound in param_bounds:
                if not self._satisfies_thread_bound(args[index], bound, assume,
                                                    visiting):
                    return False
        return True

    def _satisfies_thread_bound(self, arg: SawType, bound: str, assume,
                                visiting=None) -> bool:
        """One bound of a conditional assertion header, at one type argument.

        `visiting` must be threaded through from the walk that asked: a
        recursive type re-enters here (`enum Json { case Items(items:
        Vector<Json>) }` asks whether `Vector<Json>` is Send, whose header asks
        whether `Json` is), and a fresh set would recurse without bound. The
        key carries `want_sync`, so one set can serve both questions.
        """
        if bound == "Send":
            return self._send_sync(arg, False, visiting or set(), assume)
        if bound == "Sync":
            return self._send_sync(arg, True, visiting or set(), assume)
        return self.type_satisfies_bound(arg, bound)

    @staticmethod
    def _assumed(assume, want_sync: bool, name: str) -> bool:
        """Is this type-parameter name assumed thread-safe for this query?

        Only the legality check passes an `assume`: it asks what the derivation
        would say if the header's own bounds held, which is the only way to tell
        a field that genuinely blocks from one the header already covers.
        """
        if not assume:
            return False
        return name in assume[1 if want_sync else 0]

    def unmet_conditional_bound(self, saw_type: SawType, want_sync: bool,
                                assume=None):
        """The first `(argument, bound)` of a declared conditional assertion
        that this instantiation fails, or None.

        `extension Arc<T: Send + Sync>: UnsafeSend {}` is the shape: an `Arc`
        shares its payload, so its Send-ness needs both bounds. When the
        payload is Send but not Sync, the type is refused as not `Send`, and
        the actionable fact is the Sync bound the payload misses; this lets a
        caller name it (conformance row K31).

        Answers only for a type whose refusal really is a conditional
        assertion's; a structural refusal (a raw pointer, a plain non-Send
        field) has no single bound to name and gets None.
        """
        if saw_type is None or saw_type.kind != TypeKind.STRUCT:
            return None
        name = saw_type.struct_name
        if not name:
            return None
        bounds = self._lookup_thread_assertion(declaration_base(name),
                                               self.ASSERTION_FOR[want_sync])
        if not bounds:
            return None
        args = list(saw_type.type_args or [])
        for index, param_bounds in enumerate(bounds):
            if not param_bounds or index >= len(args) or args[index] is None:
                continue
            for bound in param_bounds:
                if not self._satisfies_thread_bound(args[index], bound, assume):
                    return (args[index], bound)
        return None

    def thread_safety_note(self, saw_type: SawType, want_sync: bool,
                           assume=None) -> str:
        """Why this type is not Send/Sync, in one sentence, or "".

        Appended to every diagnostic that refuses a type at a thread boundary.
        Two cases are worth explaining. A conditional assertion's unmet bound
        (`Arc<T: Send + Sync>` at a Send-but-not-Sync payload) is refused as
        "not `Send`" but the author's lever is the Sync bound, so the note
        names it. A cell-carrying type has its derivation blocked on purpose,
        so the note names the declaration to write and the field that made it
        necessary.
        """
        unmet = self.unmet_conditional_bound(saw_type, want_sync, assume)
        if unmet is not None:
            arg, bound = unmet
            base = declaration_base(saw_type.struct_name or "")
            derived = "Sync" if want_sync else "Send"
            note = (f" `{base}` is `{derived}` only when its payload is "
                    f"`{bound}`, and `{arg}` is not — that is the bound to "
                    f"satisfy.")
            return note + self.thread_safety_note(arg, bound == "Sync", assume)
        if saw_type is None or not self.is_cell_carrying(saw_type):
            return ""
        name = (saw_type.struct_name if saw_type.kind == TypeKind.STRUCT
                else saw_type.enum_name if saw_type.kind == TypeKind.ENUM
                else None)
        if name is None:
            return ""
        base = declaration_base(name)
        assertion = self.ASSERTION_FOR[want_sync]
        derived = "Sync" if want_sync else "Send"
        blockers = self.blocking_members(saw_type, want_sync)
        if blockers:
            fname, ftype = blockers[0]
            which = f"field `{fname}` of type `{ftype}`"
        else:
            which = "its interior cell"
        return (f" `{base}` carries an interior cell (design 186), so it "
                f"derives no `{derived}`: {which} is mutable through a shared "
                f"borrow, which the derivation cannot reason about. If the "
                f"synchronization is real but invisible to the compiler, say "
                f"so — `extension {base}: {assertion} {{}}`, beside the type, "
                f"where it can be audited.")

    def blocking_members(self, saw_type: SawType, want_sync: bool, assume=None):
        """The members that keep `saw_type` from deriving Send/Sync.

        The evidence behind the assertion legality rule and behind the error a
        cell-carrying type earns at a thread boundary with no declaration:
        naming the field makes either message actionable.
        """
        out = []
        name = (saw_type.struct_name if saw_type.kind == TypeKind.STRUCT
                else saw_type.enum_name if saw_type.kind == TypeKind.ENUM
                else None)
        if name is None:
            return out
        sym = self._lookup_struct_deep(name)
        if sym is not None:
            subst = {}
            for tp, arg in zip(sym.type_params, saw_type.type_args or []):
                subst[tp.name] = arg
            for fname, ftype in sym.fields.items():
                resolved = ftype.substitute(subst) if subst else ftype
                if not self._send_sync(resolved, want_sync, set(), assume):
                    out.append((fname, resolved))
            return out
        enum_sym = self._lookup_enum_deep(name)
        if enum_sym is not None:
            subst = {}
            for tp, arg in zip(enum_sym.type_params, saw_type.type_args or []):
                subst[tp.name] = arg
            for variant, payload in enum_sym.variants.items():
                for fname, ftype in payload:
                    resolved = ftype.substitute(subst) if subst else ftype
                    if not self._send_sync(resolved, want_sync, set(), assume):
                        out.append((f"{variant}.{fname}", resolved))
        return out

    def _lookup_enum_deep(self, name: str, _seen=None) -> Optional[EnumSymbol]:
        """The enum twin of `_lookup_struct_deep`; `_seen` is documented there."""
        result = self.lookup_enum(name)
        if result:
            return result
        if _seen is None:
            _seen = {id(self)}
        for ns in self.imported_search_namespaces():
            key = id(ns)
            if key in _seen:
                continue
            _seen.add(key)
            found = ns._lookup_enum_deep(name, _seen)
            if found:
                return found
        return None

    def _send_sync(self, saw_type: SawType, want_sync: bool, visiting: set,
                   assume=None) -> bool:
        if saw_type is None:
            return False
        kind = saw_type.kind
        # Primitives / Bool / Float are trivially thread-safe.
        if kind in self._TRIVIAL_PRIMITIVE_KINDS or kind == TypeKind.VOID:
            return True
        # String: immutable buffer + atomic refcount (designed Send/Sync payoff).
        if kind == TypeKind.STRING:
            return True
        # UnsafePointer<T> is neither; it poisons any container structurally.
        if kind == TypeKind.POINTER:
            return False
        # References/closures are not user-nameable as Send/Sync bounds;
        # closure-env Send-ness is audited at spawn sites, not here.
        if kind in (TypeKind.REFERENCE, TypeKind.FUNCTION):
            return False
        if kind == TypeKind.OPTIONAL:
            return self._send_sync(saw_type.inner_type, want_sync, visiting,
                                   assume)
        if kind == TypeKind.TUPLE:
            return all(self._send_sync(e, want_sync, visiting, assume)
                       for e in (saw_type.element_types or []))
        if kind == TypeKind.ARRAY:
            return self._send_sync(saw_type.array_element_type, want_sync,
                                   visiting, assume)
        if kind == TypeKind.STRUCT:
            name = saw_type.struct_name
            args = saw_type.type_args or []
            # Type alias flows to its underlying type.
            alias_sym = self._lookup_type_alias_deep(name)
            if alias_sym and alias_sym.aliased_type:
                return self._send_sync(alias_sym.aliased_type, want_sync,
                                       visiting, assume)
            # A declared `UnsafeSend`/`UnsafeSync` is the audited assertion
            # and answers before any structural walk. Its conditional bounds
            # are re-checked against this instantiation's arguments, so
            # `extension Mutex<T: Send>: UnsafeSync {}` promises nothing about a
            # `Mutex<File>`. There is no name-keyed list: every std wrapper
            # declares its assertion beside its type.
            if self._assertion_applies(name, saw_type, want_sync, assume,
                                       visiting):
                return True
            # A type parameter the legality check is assuming thread-safe (see
            # `_assumed`): reached only while judging a conditional header.
            if self._assumed(assume, want_sync, name):
                return True
            # Structural `Sync` derivation is blocked by an interior cell: a
            # value mutable through a shared borrow cannot be shared without
            # an argument. `Send` is untouched; a cell moves fine.
            #
            # The block sits at the cell, not at every cell-carrying type. A
            # type holding a cell directly must say `UnsafeSync` (`Atomic`,
            # `SpinLock`, `Once`); a type holding one of those derives
            # normally, because that declaration is the argument. So
            # `struct Stats { hits: Atomic<Int> }` is `Sync` with nothing
            # written.
            if want_sync and self.cell_payload(saw_type) is not None:
                return False
            struct_sym = self._lookup_struct_deep(name)
            if struct_sym is None:
                # An enum reached through a struct-kind spelling: a field,
                # payload or type argument written as a bare name arrives with
                # the struct kind whether it names a struct or an enum.
                enum_sym = self._lookup_enum_deep(name)
                if enum_sym is not None:
                    return self._enum_send_sync(enum_sym, name, args,
                                                want_sync, visiting, assume)
                # Opaque / unresolved type parameter: not structurally known.
                # (Abstract `T: Send` bodies are handled at the call site via
                # the parameter's declared bounds.)
                return False
            key = (name, tuple(str(a) for a in args), want_sync)
            if key in visiting:
                return True  # co-recursive type: assume ok on the back-edge
            visiting = visiting | {key}
            subst = {}
            for tp, arg in zip(struct_sym.type_params, args):
                subst[tp.name] = arg
            for ft in struct_sym.fields.values():
                resolved = ft.substitute(subst) if subst else ft
                if not self._send_sync(resolved, want_sync, visiting, assume):
                    return False
            return True
        if kind == TypeKind.ENUM:
            name = saw_type.enum_name
            args = saw_type.type_args or []
            if self._assertion_applies(name, saw_type, want_sync, assume,
                                       visiting):
                return True
            enum_sym = self._lookup_enum_deep(name)
            if enum_sym is None:
                return False
            return self._enum_send_sync(enum_sym, name, args, want_sync,
                                        visiting, assume)
        # TYPE_PARAM / SELF / MODULE and anything else: not structurally known.
        return False

    def _enum_send_sync(self, enum_sym, name: str, args, want_sync: bool,
                        visiting: set, assume=None) -> bool:
        """An enum is Send/Sync iff every payload it can hold is.

        Shared by both spellings that reach an enum: the ENUM kind, and the
        struct-kind bare name a field or type argument carries.
        """
        key = (name, tuple(str(a) for a in args), want_sync)
        if key in visiting:
            return True  # co-recursive type: assume ok on the back-edge
        visiting = visiting | {key}
        subst = {}
        for tp, arg in zip(enum_sym.type_params, args):
            subst[tp.name] = arg
        for payload in enum_sym.variants.values():
            for _field_name, ptype in payload:
                resolved = ptype.substitute(subst) if subst else ptype
                if not self._send_sync(resolved, want_sync, visiting, assume):
                    return False
        return True

    def get_type_assignment(self, type_name: str, trait_name: str,
                           assoc_type_name: str) -> Optional[SawType]:
        """Get an associated type assignment."""
        if type_name not in self.conformances:
            return None
        trait_map = self.conformances[type_name].get(trait_name, {})
        return trait_map.get(assoc_type_name)

    def get_type_assignments(self, type_name: str, trait_name: str) -> Dict[str, SawType]:
        """Get all associated type assignments for a type/trait conformance.

        Args:
            type_name: The type implementing the trait
            trait_name: The trait being implemented

        Returns:
            Dict mapping associated type names to their concrete types
        """
        if type_name not in self.conformances:
            return {}
        return self.conformances[type_name].get(trait_name, {})

    def get_struct_fields(self, struct_name: str) -> Optional[Dict[str, SawType]]:
        """Get the fields of a struct."""
        struct = self.lookup_struct(struct_name)
        return struct.fields if struct else None

    def get_struct_field_order(self, struct_name: str) -> Optional[List[str]]:
        """Get the field order of a struct."""
        struct = self.lookup_struct(struct_name)
        return struct.field_order if struct else None

    def has_struct(self, name: str) -> bool:
        """Check if a struct exists."""
        return self.lookup_struct(name) is not None

    def has_enum(self, name: str) -> bool:
        """Check if an enum exists."""
        return self.lookup_enum(name) is not None

    def has_function(self, name: str) -> bool:
        """Check if a function exists."""
        return name in self.functions

    def has_trait(self, name: str) -> bool:
        """Check if a trait exists."""
        return self.lookup_trait(name) is not None

    # =========================================================================
    # Visibility Checking
    # =========================================================================

    def check_visibility(self, visibility: Visibility,
                        symbol_module: Tuple[str, ...],
                        accessor_module: Tuple[str, ...],
                        package_root: Tuple[str, ...] = ()) -> bool:
        """
        Check if a symbol is accessible from another module.

        The raw decision procedure. Do not call it directly: `public(package)`
        is undecidable without a root, and a missing root is refusal here.
        `visibility_relation_allows` is the one caller: it computes the root
        from the symbol's defining module, and answers the rootless case by
        package identity before reaching this arm.

        Args:
            visibility: The symbol's visibility modifier
            symbol_module: Module path where the symbol is defined
            accessor_module: Module path that is trying to access the symbol
            package_root: The root of the current package (for public(package))

        Returns:
            True if access is allowed, False otherwise
        """
        # Public symbols are always accessible
        if visibility == Visibility.PUBLIC:
            return True

        # Private symbols are only accessible within the same module
        if visibility == Visibility.PRIVATE:
            return symbol_module == accessor_module

        # public(package) - accessible within the same package
        if visibility == Visibility.PACKAGE:
            # No root, no package: refuse. The one caller decides the rootless
            # case by identity first, so reaching here means nothing placed
            # either module and "same package" cannot be claimed.
            if not package_root:
                return False
            # Both must be under the package root
            return (symbol_module[:len(package_root)] == package_root and
                    accessor_module[:len(package_root)] == package_root)

        # public(parent) - accessible to parent module only
        if visibility == Visibility.PARENT:
            # accessor_module must be the parent of symbol_module
            if len(symbol_module) < 1:
                return False
            parent = symbol_module[:-1]
            return accessor_module == parent

        return False

    def visibility_relation_allows(self, def_module: Tuple[str, ...],
                                   visibility: Visibility,
                                   accessor: Tuple[str, ...],
                                   package_root: Optional[Tuple[str, ...]]
                                   = None) -> bool:
        """The visibility relation between two named modules, with the package
        root computed from the symbol's defining module.

        The visibility funnel: `check_visibility` above is the raw procedure,
        and it refuses a rootless `public(package)`. ENTRY POINTS:
          * `_resolve_parts.is_visible` (via `_symbol_visible`) — the
            qualified reach (`m.X`, each chain hop, each dotted `resolve()`)
          * `TypeChecker._visibility_relation_allows`, which delegates here
            with no arms of its own; through it `_member_gate_allows` (the
            field/method/type gate) and `check_module`'s selective-import and
            glob arms (`_selection_visible`)

        std is one package rooted at `("<std>",)`, and each
        `--module-path name=dir` package is rooted at `(name,)`; anything else
        falls back to this namespace's `package_root`. A module loaded by
        relative path has neither prefix, so the tier is then decided by
        package identity (manifest root or entry tree). Equal identities are
        one package; anything else, including an unplaceable module, is not.
        """
        def_module = tuple(def_module or ())
        accessor = tuple(accessor or ())
        if def_module == accessor:
            return True
        # std is its own package: a `public(package)` member of one std file is
        # reachable from any other std file, and a user module is excluded.
        if def_module and def_module[0] == "<std>":
            package_root = ("<std>",)
        # A `--module-path name=dir` package: every module under the mapped
        # dir is inside, and the entry file (never a mapped name) is outside.
        elif def_module and def_module[0] in self.mapped_packages:
            package_root = (def_module[0],)
        elif package_root is None:
            package_root = self.package_root
        # The rootless `public(package)` question (a module that arrived by
        # relative path) is answered by identity.
        if visibility == Visibility.PACKAGE and not package_root:
            own = self.package_identity(def_module)
            return own is not None and own == self.package_identity(accessor)
        return self.check_visibility(
            visibility, symbol_module=def_module, accessor_module=accessor,
            package_root=package_root)

    def package_identity(self, module_path: Tuple[str, ...]) -> Optional[str]:
        """The package a module belongs to, as an opaque token compared for
        equality. None when nothing placed it.

        Three sources, in precedence order:
          1. std is one package: every `("<std>", leaf)`.
          2. a `--module-path name=dir` package: every module path under the
             mapped name (stated here too so the accessor side is placed).
          3. `package_identities`, the driver's map of the modules it loaded:
             the file's `Saw.toml` root, or the entry tree for a manifest-less
             one (`ModuleResolver.package_identity`).

        A path the map does not hold falls back to its nearest ancestor, which
        places an inline module (path `parent + (name,)`) in its file's
        package. The entry's `()` is always in the map, so the walk terminates
        for any loaded module; an unstamped namespace answers None, which the
        funnel reads as "not the same package".
        """
        path = tuple(module_path or ())
        if path and path[0] == "<std>":
            return "<std>"
        if path and path[0] in self.mapped_packages:
            return "package:" + path[0]
        while True:
            found = self.package_identities.get(path)
            if found is not None:
                return found
            if not path:
                return None
            path = path[:-1]

    def get_symbol_visibility(self, name: str) -> Optional[Visibility]:
        """Get the visibility of a symbol by name."""
        for _lookup in (self.lookup_struct, self.lookup_enum):
            sym = _lookup(name)
            if sym is not None:
                return sym.visibility
        if name in self.functions:
            return self.functions[name].visibility
        for _lookup in (self.lookup_trait, self.lookup_type_alias):
            sym = _lookup(name)
            if sym is not None:
                return sym.visibility
        return None

    # =========================================================================
    # Generic Instantiation Tracking
    # =========================================================================

    def mark_instantiated(self, mangled_name: str):
        """Mark a generic instantiation as generated."""
        self.instantiated.add(mangled_name)

    def is_instantiated(self, mangled_name: str) -> bool:
        """Check if a generic instantiation has been generated."""
        return mangled_name in self.instantiated

    # =========================================================================
    # Namespace Merging
    # =========================================================================

    def merge_into(self, other: 'Namespace', source_label: Optional[str] = None,
                   collisions: Optional[List[Tuple[str, str, str, str]]] = None,
                   exclude: Optional[set] = None):
        """
        Merge another namespace's symbols into this one.

        Used for codegen when combining per-module namespaces into a unified
        namespace. Existing symbols in this namespace are not overwritten.

        Collision policy: merging is first-wins, but dropping a different
        symbol object under an already-taken name is a genuine ambiguity (two
        modules each defining `foo`), so it is reported. Builtins are shared by
        reference across every module namespace (each module clones them via
        `merge_into`), so re-merging the same object is benign and never flagged;
        only a name bound to a *distinct* object counts as a collision.

        Args:
            source_label: A human-readable label for `other` (e.g. a module path
                string). When provided, each first-seen symbol records this label
                as its provenance so a later collision can name both sides.
            collisions: Optional accumulator; when provided, each detected
                collision appends a ``(category, name, existing_label, new_label)``
                tuple. Collisions are checked for the value symbol categories
                (structs, enums, functions, traits, type aliases), not for
                module aliases or generic AST storage.
        """
        def _module_local(sym) -> bool:
            """Whether `sym` is a module-private declaration carrying a
            module-local codegen symbol. It cannot be named from another module
            and does not share an LLVM name with a same-named private
            declaration elsewhere, so a shared name is not a collision."""
            return (getattr(sym, 'visibility', None) == Visibility.PRIVATE
                    and bool(getattr(sym, 'mangled_name', "")))

        def _distinct_definitions(a, b) -> bool:
            """Whether two same-named free functions from different modules are
            two definitions the merge can hold at once.

            Free functions carry module identity, so two modules owning one
            name is not a merge event, provided they emit distinct LLVM symbols
            (`symbol_base` module-tags every name more than one module
            declares). The same codegen symbol is a real collision, reported."""
            amod = tuple(getattr(a, 'def_module', ()) or ())
            bmod = tuple(getattr(b, 'def_module', ()) or ())
            if amod == bmod:
                return False
            asym = getattr(a, 'mangled_name', "") or getattr(
                a, 'symbol_base', "") or None
            bsym = getattr(b, 'mangled_name', "") or getattr(
                b, 'symbol_base', "") or None
            return asym is not None and bsym is not None and asym != bsym

        def _merge(category: str, dst: Dict[str, Any], src: Dict[str, Any],
                   private_is_local: bool = False,
                   module_keyed: bool = False):
            for name, sym in src.items():
                # A std symbol whose module is not compiled into this program
                # (non-imported import-required std) is skipped, so a user type
                # of the same name does not collide with it.
                if exclude and name in exclude:
                    continue
                existing = dst.get(name)
                if existing is None:
                    dst[name] = sym
                    if source_label is not None:
                        self._provenance[name] = source_label
                elif existing is not sym and collisions is not None:
                    if private_is_local and (_module_local(sym)
                                             or _module_local(existing)):
                        continue
                    if module_keyed and _distinct_definitions(sym, existing):
                        continue
                    prev = self._provenance.get(name, "<unknown>")
                    collisions.append((category, name, prev,
                                       source_label if source_label is not None
                                       else "<unknown>"))

        # The four type tables are keyed by type identity, so two modules'
        # `Header`s never meet here. A genuine collision is one identity bound
        # to two distinct symbols (a module declaring a name twice). The
        # ambiguity of a bare `Header` exported by two modules is not a merge
        # event; it is the use-site error carried by `type_names` /
        # `ambiguous_types` below.
        _merge("struct", self.structs, other.structs)
        _merge("enum", self.enums, other.enums)
        _merge("function", self.functions, other.functions,
               private_is_local=True, module_keyed=True)
        # Carry each name's full overload set across the merge (first-wins per
        # name, matching the representative merge above).
        for _name, _lst in other.function_overloads.items():
            if _name not in self.function_overloads:
                self.function_overloads[_name] = list(_lst)
        # The identity-keyed storage travels too, keyed by defining module, so
        # a module's own declarations stay answerable after the merge and two
        # modules' entries never collide. The binding view
        # (`function_name_modules`) deliberately does not travel: what a bare
        # name means is each namespace's own business, and carrying std's
        # bindings into a user module would bare-bind every std function there.
        for _mod, _tbl in other.module_function_overloads.items():
            _dst = self.module_function_overloads.setdefault(_mod, {})
            for _n, _lst in _tbl.items():
                _dst.setdefault(_n, list(_lst))
        _merge("trait", self.traits, other.traits)
        _merge("type alias", self.type_aliases, other.type_aliases)
        # Statics follow the same collision rule as the other value symbols:
        # two modules each defining a distinct public static of one name is an
        # ambiguity, reported. A module-private one is not: it is unnameable
        # from outside and carries a module-local LLVM global.
        _merge("static", self.statics, other.statics, private_is_local=True)
        # The per-module overlays travel too, keyed by defining module, so a
        # std file's private constants stay reachable from that file's own
        # bodies after the merge and from nowhere else.
        for _mod, _tbl in other.module_statics.items():
            _dst = self.module_statics.setdefault(_mod, {})
            for _n, _s in _tbl.items():
                _dst.setdefault(_n, _s)
        # The source-name -> identity view travels too, so the merged namespace
        # can still answer a bare-name query (codegen asks by identity, but the
        # place lowering and the re-entered front half ask by name). Two modules
        # binding one name to two identities marks the name ambiguous.
        for _n, _ident in other.type_names.items():
            if exclude and (_n in exclude or _ident in exclude):
                continue
            self.bind_type_name(_n, _ident, "type", source_label)
        # The per-module private type-name views travel the same way.
        for _mod, _tbl in other.module_type_names.items():
            _dst = self.module_type_names.setdefault(_mod, {})
            for _n, _ident in _tbl.items():
                _dst.setdefault(_n, _ident)
        for _n, _amb in other.ambiguous_types.items():
            self.ambiguous_types.setdefault(_n, _amb)
        for name, sym in other.modules.items():
            if name not in self.modules:
                self.modules[name] = sym
        # Merge conformances. `exclude` applies to every table below too: they
        # are keyed by type name, and a std module this program does not
        # compile in must contribute nothing under a name a user type may hold
        # (its conformances or generic template would attach to the user's
        # type).
        def _excluded(key) -> bool:
            return bool(exclude) and key in exclude

        for type_name, iface_map in other.conformances.items():
            if _excluded(type_name):
                continue
            if type_name not in self.conformances:
                self.conformances[type_name] = {}
            for iface_name, assoc_types in iface_map.items():
                if iface_name not in self.conformances[type_name]:
                    self.conformances[type_name][iface_name] = assoc_types
        # The declared thread-safety assertions travel with the conformances;
        # the orphan rule pins each to one module, so first-wins can never drop
        # a competing declaration.
        for type_name, trait_map in other.thread_assertions.items():
            if _excluded(type_name):
                continue
            dst = self.thread_assertions.setdefault(type_name, {})
            for trait_name, bounds in trait_map.items():
                dst.setdefault(trait_name, bounds)
        # Merge generic AST storage
        for name, ast in other.generic_functions.items():
            if name not in self.generic_functions and not _excluded(name):
                self.generic_functions[name] = ast
        for name, ast in other.generic_structs.items():
            if name not in self.generic_structs and not _excluded(name):
                self.generic_structs[name] = ast
        for name, ast in other.generic_enums.items():
            if name not in self.generic_enums and not _excluded(name):
                self.generic_enums[name] = ast
        for name, exts in other.generic_extensions.items():
            if _excluded(name):
                continue
            if name not in self.generic_extensions:
                self.generic_extensions[name] = exts
            else:
                # Extend the list of extensions
                self.generic_extensions[name].extend(exts)


class StdLeafNamespace(Namespace):
    """The namespace a std module qualifier resolves through (design 150).

    Every std file is its own module; `import std.time` binds `time` as a
    qualifier over exactly that file's declarations, as `import pkg.io` binds
    `io`. This view holds those declarations as shared symbol objects, never
    copies, so identity and mangling are unchanged.

    Visibility is membership. std's top-level declarations carry no `public`
    marker (the prelude gate decides whether user source may name one), so an
    ordinary check would refuse every std type through its own qualifier. The
    names here are exactly `_std_file_symbols[leaf]`, the set the glob form
    exposes bare, so being in the view is the whole permission. The member
    gate still applies: reaching `time.Instant` says nothing about which of
    its fields and methods are public.
    """

    is_std_leaf: bool = True

    def check_visibility(self, visibility: 'Visibility',
                         symbol_module: Tuple[str, ...],
                         accessor_module: Tuple[str, ...],
                         package_root: Tuple[str, ...] = ()) -> bool:
        return True

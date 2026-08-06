"""
Saw Language Type Checker
Performs type checking and semantic analysis on the AST.
"""

import itertools
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from ast_nodes import (
    Program, Function, Block, Statement, Expression,
    LetStatement, AssignStatement, ReturnStatement, ExpressionStatement,
    WhileExpr, BreakStatement, ContinueStatement, ForLoop, RangeExpr,
    IntLiteral, FloatLiteral, BoolLiteral, StringLiteral, StringInterpolation, Identifier,
    BinaryOp, UnaryOp, MoveExpr, CastExpr, FunctionCall, IfExpr, IfLetExpr,
    TupleLiteral, TupleIndex, ArrayLiteral, ArrayIndex,
    MemberAccess, StructInit,
    NoneLiteral, ForceUnwrap, NilCoalesce, OptionalChain,
    GuardLetStatement,
    Struct, StructField,
    Enum, EnumVariant, EnumInit, MatchExpr, MatchArm,
    Extension, Method, MethodCall, SelfExpr,
    Trait, TraitMethod, AssociatedType, TypeAssignment, TypeDefinition,
    ExternFunction, ExternBlock,
    SawType, TypeKind, Parameter, Argument, TypeParameter,
    ClosureExpr, ClosureParam,
    ImportDecl, Visibility
)
from errors import ErrorReporter, ErrorKind
from target_info import platform_int_width
from namespace import (
    Namespace, SymbolKind,
    FunctionSymbol, StructSymbol, EnumSymbol, TraitSymbol, TypeAliasSymbol,
    TraitMethodSymbol
)
from .types import TypeUtilsMixin
from .registration import RegistrationMixin
from .statements import StatementsMixin
from .expressions import ExpressionsMixin
from .effects import EffectsMixin
from .places import PlacesMixin


_BINDING_ID_COUNTER = itertools.count(1)


@dataclass
class VariableInfo:
    """Information about a variable in scope."""
    type: SawType
    mutable: bool
    line: int
    column: int
    # A stable identity for this BINDING, used to key move state (design 126 R2).
    # Previously that map was keyed by `id(var_info)`, which forced the map to
    # keep the object alive so the address could not be recycled onto a later
    # binding; an explicit counter removes both the address dependence and that
    # keep-alive obligation.
    binding_id: int = field(default_factory=lambda: next(_BINDING_ID_COUNTER))


class Scope:
    """A lexical scope containing variable bindings."""

    def __init__(self, parent: Optional['Scope'] = None):
        self.parent = parent
        self.variables: Dict[str, VariableInfo] = {}

    def define(self, name: str, info: VariableInfo) -> bool:
        """Define a variable in this scope. Returns False if already defined."""
        if name in self.variables:
            return False
        self.variables[name] = info
        return True

    def lookup(self, name: str) -> Optional[VariableInfo]:
        """Look up a variable, checking parent scopes."""
        if name in self.variables:
            return self.variables[name]
        if self.parent:
            return self.parent.lookup(name)
        return None

    def lookup_local(self, name: str) -> Optional[VariableInfo]:
        """Look up a variable only in this scope."""
        return self.variables.get(name)


class TypeChecker(ExpressionsMixin, StatementsMixin, RegistrationMixin, TypeUtilsMixin, EffectsMixin, PlacesMixin):
    """Type checks a Saw program."""

    def __init__(self, reporter: ErrorReporter, freestanding: bool = False,
                 runtime_build: bool = False, post_transform: bool = False,
                 no_hidden_alloc: bool = False,
                 target_triple: Optional[str] = None):
        self.reporter = reporter
        # design 135: `--no-hidden-alloc`. Forbids the allocations the COMPILER
        # inserts that no source construct names — the escaping-closure
        # environment, the String a `"{x}"` interpolation builds, the `to_string()`
        # a single-argument `print` of a user `Printable` synthesizes. Every
        # allocation the SOURCE names (a `Vector.push`, a collection literal, a
        # `Box<any Error>` in a written signature, `spawn`) is untouched. The
        # audit table in LANGUAGE_SPEC.md is the full classification.
        self.no_hidden_alloc = no_hidden_alloc
        # design 47 + DF-137d/DF-140a: platform `Int`/`UInt` are pointer-width,
        # so which bare literals fit them is a fact about the EFFECTIVE target.
        # Carried here (not just in codegen) so the literal range check rejects
        # `0x80000000` for riscv32 instead of letting it wrap to a negative.
        self.target_triple = target_triple
        self.platform_int_width = platform_int_width(target_triple)
        # design 130: True on the RE-CHECK that follows the coroutine transform.
        # The transform rewrites user bodies in place — a held `&var` param
        # becomes a frame-resident `UnsafePointer<T>`, a spawned task reaches its
        # group through an `UnsafeConstPointer<TaskGroup>` — so the post-transform
        # AST attributes compiler-minted pointers to the user's own function. The
        # trigger rule therefore judges the SOURCE program, on the first pass
        # only; everything the transform adds is synthesized and exempt anyway.
        self.post_transform = post_transform
        # Freestanding profile (design 19/20): gates hosted-only facilities such
        # as Float formatting in print (dtoa is not available without libc).
        self.freestanding = freestanding
        # Runtime-build mode (design 113b): the module IS a runtime — it may
        # `@export` the frozen `__saw_rt_*` ABI set, and it is sync-only (it sits
        # below the machinery that suspends). Loosens the `@export` reservation
        # for exactly those names; every other reserved name stays rejected.
        self.runtime_build = runtime_build
        self.current_scope: Scope = Scope()
        self.current_function: Optional[Function] = None
        self.current_method: Optional['Method'] = None  # Track current method for 'self'
        # Type substitution map for specialized extensions (e.g., {"T": String})
        self.current_type_subst: Dict[str, SawType] = {}
        # Track return statements found in current function
        self.found_return_with_value: bool = False
        # Track loop nesting depth for break/continue validation
        self.loop_depth: int = 0
        # design 130 trigger rule: the first contact the function currently being
        # checked made with an unsafe type, as (line, column, why, type name), or
        # None. A closure body gets its own scope — rule 3 judges a closure on
        # its OWN body, so contacts never leak either way across the boundary.
        self._unsafe_contact = None
        # design 132 unit A: the scope each enclosing closure body opened,
        # innermost last. A name an assignment target resolves to ABOVE the
        # innermost entry arrived by VALUE capture, so writing it would hit the
        # per-call copy of the env and be discarded (DF-122a).
        self._closure_scopes: List[Scope] = []
        # Track break value types for each loop level
        # Each entry is (expected_type: Optional[SawType], is_infinite: bool, has_break: bool)
        self.loop_break_info: List[Tuple[Optional[SawType], bool, bool]] = []
        # Per-function, scope-aware move state for use-after-move detection.
        # Keyed by the binding's `VariableInfo.binding_id`, so that same-named
        # bindings in different functions/scopes never interact and a `let`/`var`
        # shadow gets fresh state.
        # value = (var_info, name, move_line, move_column)
        self.moved_bindings: Dict[int, Tuple['VariableInfo', str, int, int]] = {}
        # Structs whose copy() is compiler-derived (memberwise), checked for
        # NoCopy fields after all conformances are registered.
        self._derived_copy_structs: set[str] = set()
        # Enums whose copy() is compiler-derived payload-deep (design 139): a
        # declared `@synthesize extension E: ImplicitCopy|ExplicitCopy {}`.
        self._derived_copy_enums: set[str] = set()
        # Structs/enums whose equals() (==) is compiler-derived (design 32),
        # checked for non-Equatable fields/payloads after all conformances are
        # registered.
        self._derived_equals_types: set[str] = set()
        # Structs/enums whose compare() (< <= > >=) is compiler-derived
        # (design 48), checked for non-Comparable fields/payloads and the
        # Equatable requirement after all conformances are registered.
        self._derived_compare_types: set[str] = set()
        # Structs/enums whose hash() is compiler-derived (design 48), checked for
        # non-Hashable fields/payloads after all conformances are registered.
        self._derived_hash_types: set[str] = set()
        # Every type declaring `extension T: Comparable` / `Hashable` (derived or
        # custom): each must also conform to Equatable (the "requires Equatable"
        # rule), verified after all conformances are registered.
        self._comparable_types: set[str] = set()
        self._hashable_types: set[str] = set()
        # Track if we're inside a try-catch block (errors go to catch, not caller)
        self.in_try_catch_block: bool = False

        # design 22 effect system: whole-program suspend analysis state.
        self._effect_init()

        # design 58: whole-program C-export symbol table for hygiene checks
        # (duplicate exported symbols across the compilation unit). Accumulated
        # across every module the shared checker instance visits. Maps the
        # requested C symbol -> (declaration name, line, column, source_file).
        self._export_symbol_table: Dict[str, Tuple[str, int, int, Optional[str]]] = {}

        # Unified namespace (Phase 0 of module system)
        # Populated in parallel with legacy dicts during migration
        self.namespace = Namespace()

        # Current module path during multi-module type checking
        self.current_module_path: Tuple[str, ...] = ()

        # Design 142: the modules the file being checked DIRECTLY imports, as
        # defining-module tuples (a user `import a.b` -> ("a", "b"); a
        # `import std.data` -> ("<std>", "data"), matching `_vis_module_for_source`).
        # Extension-method lookup consults exactly this set plus the current
        # module and the receiver type's own module — a transitive dependency
        # injects nothing. Empty in the single-file compilation path, where every
        # declaration shares the `()` module.
        self.current_direct_imports: Set[Tuple[str, ...]] = set()

        # Register built-in functions
        self._register_builtins()

    def _get_current_source_file(self) -> Optional[str]:
        """Get the source file from the current method or function context."""
        if self.current_method and hasattr(self.current_method, 'source_file'):
            return self.current_method.source_file or None
        if self.current_function and hasattr(self.current_function, 'source_file'):
            return self.current_function.source_file or None
        return None

    # ------------------------------------------------------------------ #
    # Member visibility (design 80/82) — module identity for the field/method
    # gate.
    #
    # std/builtin declarations are merged into ONE AST for codegen (the prelude
    # "bypass"), so their registration module_path is `()` — indistinguishable
    # from user code. For the ACCESS gate we key each declaration's defining
    # module on its SOURCE FILE. Design 82 retired the single-`("<std>",)`
    # coalescing: each std file is now its OWN module `("<std>", "<leaf>")`
    # (builtin.saw + std/vector.saw are DISTINCT modules to each other), so a
    # private member of one std file is invisible to another — exactly like user
    # modules. Genuinely-shared std internals are marked `public(package)` (std
    # is the package, rooted at `("<std>",)`); the rest of std reaches an API
    # only through its owning module's `public` surface. This kills the prelude
    # bypass for visibility only (codegen's compiler-known-ness is untouched).
    # ------------------------------------------------------------------ #
    def _vis_module_for_source(self, source_file: Optional[str]) -> Tuple[str, ...]:
        import os
        if not source_file:
            return self.current_module_path
        try:
            norm = os.path.abspath(source_file)
        except Exception:
            return self.current_module_path
        std_prefix = getattr(self, '_std_dir_prefix', None)
        if std_prefix is None:
            sawc_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            std_prefix = os.path.join(sawc_dir, 'std') + os.sep
            self._std_dir_prefix = std_prefix
        base = os.path.basename(norm)
        if norm.startswith(std_prefix) or base == 'builtin.saw':
            leaf = base[:-4] if base.endswith('.saw') else base
            return ("<std>", leaf)
        return self.current_module_path

    def _accessor_vis_module(self) -> Tuple[str, ...]:
        """The defining module of the code currently being type-checked (the
        accessor), for the member-visibility gate."""
        return self._vis_module_for_source(self._get_current_source_file())

    def _in_synthesized_context(self) -> bool:
        """Whether the code currently being checked is compiler-synthesized
        (coroutine-transform output). Such code accesses std/frame internals by
        construction and is EXEMPT from the member-visibility gate (design 80) —
        the gate enforces source-level access only. Provenance-based, not by name."""
        if self.current_method is not None and getattr(
                self.current_method, 'is_synthesized', False):
            return True
        if self.current_function is not None and getattr(
                self.current_function, 'is_synthesized', False):
            return True
        return False

    # ===== No hidden allocations (design 135) =====

    def _hidden_alloc_gate(self) -> bool:
        """Whether `--no-hidden-alloc` applies to the code being checked here.

        The gate judges USER SOURCE, on the first pass only. std's own bodies are
        already written on the alloc-free path (the design-135 audit found no
        interpolation anywhere in `sawc/std/` or `builtin.saw`), and the
        coroutine transform's output is compiler-authored by construction — a
        spawned task's frame box is the `spawn` the user did write, counted once
        at its call site rather than again at every rewritten hop."""
        if not self.no_hidden_alloc:
            return False
        if getattr(self, '_checking_builtins', False):
            return False
        if self.post_transform or self._in_synthesized_context():
            return False
        if self._accessor_vis_module()[:1] == ("<std>",):
            return False
        return True

    def _hidden_alloc_error(self, what: str, line: int, column: int,
                            hint: str) -> None:
        """Report one design-135 hidden-allocation site.

        `what` names the construct and what it allocates; `hint` names the
        spelling that does not."""
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"{what} — `--no-hidden-alloc` forbids allocations the source "
            f"does not name",
            line, column, hint=hint)

    # ===== Unsafe surface (design 130) =====
    #
    # Unsafety is a property of TYPES, declared by `unsafe struct` (plus the
    # built-in raw pointers), and a function is `unsafe` when it NAMES, BINDS,
    # RECEIVES or RETURNS a value of one — rule 3. Deliberately broader than
    # "performs a deref": merely reading `self.buffer` into an iterator is what
    # made bugs C2/C5 invisible under design 81's line-level marker.
    #
    # Two things the rule pointedly does NOT do. Unsafety is not TRANSITIVE
    # across types (rule 4): `Vector` holds an `UnsafePointer` field and is a
    # safe type, so only the methods touching the field are unsafe. And it does
    # not propagate along CALL edges (rule 6): an unsafe function is the reviewed
    # wrapper, and calling one from safe code needs no ceremony. What makes that
    # sound is rule 7 — a function whose parameters are all safe types must be
    # sound for every input, and a precondition is expressed by taking an
    # unsafe-typed parameter, which drags the obligation into the caller through
    # rule 3 itself.

    def _type_is_unsafe(self, t) -> bool:
        """Whether `t` IS an unsafe type: a raw pointer (`UnsafePointer<T>` /
        `UnsafeConstPointer<T>`) or a struct declared `unsafe struct`."""
        if t is None:
            return False
        if t.kind == TypeKind.POINTER:
            return True
        if t.kind == TypeKind.STRUCT and t.struct_name:
            info = self.get_struct_info(t.struct_name)
            return info is not None and getattr(info, 'is_unsafe', False)
        return False

    def _first_unsafe_type(self, t):
        """The first unsafe type in `t`'s own tree, or None. Walks into
        optionals, references, arrays, tuples, generic arguments and closure
        signatures — every place a value of that type can reach the code naming
        `t`. Struct FIELDS are NOT walked: unsafety is not transitive."""
        if t is None:
            return None
        if self._type_is_unsafe(t):
            return t
        for sub in (getattr(t, 'inner_type', None),
                    getattr(t, 'array_element_type', None),
                    getattr(t, 'func_return_type', None)):
            found = self._first_unsafe_type(sub)
            if found is not None:
                return found
        for group in ('type_args', 'element_types', 'param_types'):
            for sub in (getattr(t, group, None) or []):
                found = self._first_unsafe_type(sub)
                if found is not None:
                    return found
        return None

    def _type_tree_has_unsafe(self, t) -> bool:
        return self._first_unsafe_type(t) is not None

    def _fn_signature_names_unsafe(self, t) -> bool:
        """Whether a FUNCTION type's own signature — a parameter or the return —
        names an unsafe type.

        design 136: this is exactly what the `unsafe` effect on a function type
        means. The effect has one job, handing an unsafe value into an unnamed
        function (the `with_raw` shape), so it is present precisely when the
        signature demands it. Deriving it from the signature rather than trusting
        a written keyword is what keeps one contract from having a marked and an
        unmarked spelling, and with it any variance question between the two.
        """
        if t is None or t.kind != TypeKind.FUNCTION:
            return False
        for pt in (t.param_types or []):
            if self._type_tree_has_unsafe(pt):
                return True
        return self._type_tree_has_unsafe(t.func_return_type)

    def _note_unsafe_contact(self, t, node, what: str) -> None:
        """Record that the function being checked touched an unsafe type. Only
        the FIRST contact is kept — it is the one the diagnostic points at, and
        one message per function beats one per pointer access."""
        if self._unsafe_contact is not None:
            return
        found = self._first_unsafe_type(t)
        if found is None:
            return
        self._unsafe_contact = (getattr(node, 'line', 0),
                                getattr(node, 'column', 0), what, str(found))

    def _unsafe_check_exempt(self, node) -> bool:
        """Compiler-synthesized bodies are exempt from the trigger rule: the
        coroutine transform's frames and the derived copy/equals/compare/hash
        bodies traffic in whatever their source type holds, and there is no
        declaration for an author to mark."""
        return (self.post_transform
                or getattr(node, 'is_synthesized', False)
                or getattr(node, 'is_derived_copy', False)
                or getattr(node, 'is_derived_equals', False)
                or getattr(node, 'is_derived_compare', False)
                or getattr(node, 'is_derived_hash', False))

    def _enter_unsafe_scope(self, node, param_types, return_type):
        """Begin the trigger-rule check for a function/method/closure body.
        Returns the saved outer state, which the matching exit restores.

        Signature contact is recorded up front, so a function that RECEIVES or
        RETURNS an unsafe value is unsafe whether or not its body does anything
        with it."""
        saved = self._unsafe_contact
        self._unsafe_contact = None
        for pt in (param_types or []):
            self._note_unsafe_contact(
                pt, node, "its signature receives a value of unsafe type")
        self._note_unsafe_contact(
            return_type, node, "its signature returns a value of unsafe type")
        return saved

    def _exit_unsafe_scope(self, node, saved, what: str, name: str,
                           fixit: str = None) -> None:
        """Finish the trigger-rule check and restore the outer state. An
        undeclared function that touched an unsafe type is a clean error naming
        the type and the fix; the converse is allowed — `unsafe` where the rule
        would not require it is a promise about the contract, not a lie, and a
        conformer of an `unsafe` trait requirement needs exactly that."""
        contact = self._unsafe_contact
        self._unsafe_contact = saved
        if contact is None or getattr(node, 'is_unsafe', False):
            return
        if self._unsafe_check_exempt(node):
            return
        line, column, why, type_name = contact
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"{what} `{name}` is not declared `unsafe`, but {why} "
            f"(`{type_name}`)",
            line, column,
            hint=f"write `{fixit or ('func ' + name + '(...) unsafe')}` — the "
                 f"unsafety belongs in the signature where every caller can see "
                 f"it; if the operation is sound for every input, keep the "
                 f"wrapper unsafe and expose a safe one that checks its "
                 f"arguments",
            # The verdict runs during teardown, after `current_method` /
            # `current_function` are cleared, so `_error`'s auto-detection would
            # fall back to the ENTRY module and point a multi-module diagnostic
            # at an unrelated file. Name the declaration's own file.
            source_file=getattr(node, 'source_file', None) or None,
        )

    def _member_gate_allows(self, def_module: Tuple[str, ...],
                            visibility: Visibility) -> bool:
        """Whether the code currently being checked may reach a member with the
        given defining module + visibility (design 80). Same-module access is
        always allowed; cross-module follows the top-level visibility rules."""
        accessor = self._accessor_vis_module()
        if def_module == accessor:
            return True
        # std is its own package (design 82): a `public(package)` member of one
        # std file is reachable from any other std file. Root the package at
        # `("<std>",)` when the member is std-defined, so cross-std-file package
        # sharing works and a user module (not under `("<std>",)`) is excluded.
        if def_module and def_module[0] == "<std>":
            package_root = ("<std>",)
        else:
            package_root = getattr(self.namespace, 'package_root', ())
        return self.namespace.check_visibility(
            visibility, symbol_module=def_module, accessor_module=accessor,
            package_root=package_root)

    # ------------------------------------------------------------------ #
    # Extension scoping (design 142).
    #
    # Design 80 asked only "is this member's visibility permissive enough?".
    # That let ANY module in the link inject its `public` extension methods onto
    # a type for the whole program: a transitive dependency you never imported —
    # and cannot name — monkey-patched your types, with silent cross-dependency
    # collisions and an add-a-dependency-changes-resolution hazard behind it.
    #
    # Method lookup now consults extensions from exactly three places: the
    # current module, the modules this file DIRECTLY imports, and the receiver
    # type's own defining module (its inherent API — a value can reach you
    # without the import). So `public` on an extension means what it means
    # everywhere else: importers of my module get this.
    #
    # Two exemptions, both principled rather than pragmatic:
    #  - a method satisfying a trait requirement is reached through the
    #    CONFORMANCE, which the orphan rule pins to the type's or the trait's own
    #    module and which is therefore coherent program-wide (design 142 part 2);
    #  - std is one library and one scoping domain. Its files are separate
    #    modules for privacy (design 82), but they extend each other's types on
    #    purpose (`std.string` defines `Vector<String>.join`), and the prelude
    #    rules already govern which std NAMES a file may write unimported.
    # ------------------------------------------------------------------ #
    def _ext_scope_allows(self, method_info, struct_info) -> bool:
        """Whether an extension method is IN SCOPE for the code being checked
        (design 142). Orthogonal to `_member_gate_allows`, which asks whether its
        visibility permits the access; a method must pass both."""
        # The coroutine transform re-checks its own output, splicing bodies from
        # every module into one AST — provenance no longer describes an import
        # graph there. The rule is a source-level one, like the unsafe trigger.
        if self.post_transform or self._in_synthesized_context():
            return True
        if getattr(method_info, 'satisfies_trait', False):
            return True
        def_module = getattr(method_info, 'def_module', ()) or ()
        if not def_module:
            # Single-file compilation: every declaration shares the `()` module.
            return True
        if def_module[:1] == ("<std>",):
            return True
        accessor = self._accessor_vis_module()
        if def_module == accessor:
            return True
        # A nested module sees its ancestors' declarations by construction (their
        # public symbols are injected into its namespace, not imported).
        if accessor[:len(def_module)] == def_module:
            return True
        recv_module = getattr(struct_info, 'def_module', ()) or ()
        if def_module == recv_module:
            return True
        return def_module in self.current_direct_imports

    @staticmethod
    def _module_label(module: Tuple[str, ...]) -> str:
        """How a defining module is spelled in a diagnostic — the same text the
        reader would put after `import`."""
        if module[:1] == ("<std>",):
            return "std." + ".".join(module[1:])
        return ".".join(module) if module else "this module"

    def _process_std_import(self, imp, ns, builtin_namespace) -> Optional[str]:
        """Make the requested std symbols accessible for an `import std.<module>`
        (design 82 Part B). The symbols already live in `builtin_namespace` and
        are merged into `ns`; a prelude import simply un-gates the requested
        names (and registers the module for qualified `mod.Name` access). Non-
        prelude std stays compiler-known but hidden until imported.

        Returns the std module's leaf name (`data` for `import std.data`), which
        the caller records as a direct import, or None if the import was
        malformed."""
        file_symbols = getattr(builtin_namespace, '_std_file_symbols', {}) or {}
        # `import std.net[...]` -> leaf module = the component after `std`.
        path = list(imp.path)
        # Drop a trailing '*' (glob form `import std.net.*`).
        if path and path[-1] == '*':
            path = path[:-1]
        if len(path) < 2:
            self._error(
                ErrorKind.UNKNOWN_TYPE,
                "`import std` needs a module (e.g. `import std.net`)",
                getattr(imp, 'line', 0), getattr(imp, 'column', 0))
            return None
        leaf = path[1]
        available = file_symbols.get(leaf)
        if available is None:
            self._error(
                ErrorKind.UNKNOWN_TYPE,
                f"unknown std module `std.{leaf}`",
                getattr(imp, 'line', 0), getattr(imp, 'column', 0),
                hint="std modules are: " + ", ".join(sorted(file_symbols)))
            return None

        def _expose(name, local):
            # Register an aliased copy so the local name resolves to the symbol
            # (unaliased just un-gates the already-merged symbol).
            if local != name:
                for table, reg in (
                    (ns.structs, ns.register_struct),
                    (ns.enums, ns.register_enum),
                    (ns.functions, ns.register_function),
                    (ns.traits, ns.register_trait),
                    (getattr(ns, 'type_aliases', {}), getattr(ns, 'register_type_alias', None)),
                    (ns.statics, ns.register_static),
                ):
                    if name in table and reg is not None and local not in table:
                        reg(local, table[name])
                        break
            ns.make_accessible(local)

        if imp.symbols:
            aliases = imp.symbol_aliases or {}
            for sym_name in imp.symbols:
                if sym_name not in available:
                    self._error(
                        ErrorKind.UNKNOWN_TYPE,
                        f"`{sym_name}` is not defined in `std.{leaf}`",
                        getattr(imp, 'line', 0), getattr(imp, 'column', 0),
                        hint="available: " + ", ".join(sorted(available)))
                    continue
                _expose(sym_name, aliases.get(sym_name, sym_name))
        else:
            # Whole-module import: expose every symbol the module defines.
            for sym_name in available:
                _expose(sym_name, sym_name)

        # NOTE: unlike a user-module import, a std prelude import does NOT
        # register a `leaf.Name` module alias — the leaf name (`data`, `net`,
        # `path`) is a common local-variable name, and a module alias would
        # shadow it (`data.push(...)` misparsed as module access). Bare names
        # (and `.{A, B}`) are the supported std import forms.
        return leaf

    def _decl_is_std_sourced(self, node) -> bool:
        """Whether a declaration comes from a std/builtin source file. Used so a
        std method/function body re-checked in a USER compile (e.g. a suspending
        std method the coroutine transform splices into the entry AST, design 84)
        may still reach std internals — the accessibility gate applies to user
        SOURCE, not to std's own already-validated bodies."""
        sf = getattr(node, 'source_file', None)
        if not sf:
            return False
        return self._vis_module_for_source(sf)[:1] == ("<std>",)

    def _shadows_hidden_std(self, name: str) -> bool:
        """Whether a user declaration of `name` shadows a HIDDEN (non-prelude,
        not-yet-imported) std symbol merged in from the builtins (design 82
        Part B). Such a redefinition is allowed — the std symbol was never in the
        user's namespace, so there is no real clash. std's own bodies
        (allow_all_access) and already-accessible prelude/imported names are not
        shadowable this way."""
        ns = self.namespace
        if getattr(self, '_checking_builtins', False):
            return False
        if name in ns.directly_accessible:
            return False
        return name in getattr(self, '_std_symbol_file', {})

    def _std_name_gated(self, name: str, line: int, column: int) -> bool:
        """Prelude discipline (design 82 Part B): reject a bare source reference
        to a NON-PRELUDE std symbol (e.g. `TcpStream`, `File`, `IoError`) that
        has not been imported, with a "did you mean import" hint. Returns True
        (and reports) when the name is blocked; False when it is fine to resolve
        (prelude, imported, a user symbol, or synthesized/std-internal code).

        The name stays compiler-known — this gates only whether USER SOURCE may
        name it without `import std.<module>`."""
        ns = self.namespace
        # std's own bodies reach std internals by construction; synthesized coro
        # output reaches std/frame internals by construction — both are exempt.
        if getattr(self, '_checking_builtins', False):
            return False
        if self._in_synthesized_context():
            return False
        if name in ns.directly_accessible:
            return False
        owner = getattr(self, '_std_symbol_file', {}).get(name)
        if owner is None:
            return False  # not a std symbol — leave normal resolution/errors
        # A user module that defines (or imports) its own symbol of this name has
        # made it directly accessible above, so we never reach here for it — the
        # gate fires only for a bare reference to a hidden std symbol.
        self._error(
            ErrorKind.UNKNOWN_TYPE,
            f"`{name}` is not in the prelude and must be imported",
            line, column,
            hint=f"add `import std.{owner}.{{{name}}}` (or `import std.{owner}`)",
        )
        return True

    def _vis_word(self, visibility: Visibility) -> str:
        return {
            Visibility.PUBLIC: "public",
            Visibility.PACKAGE: "public(package)",
            Visibility.PARENT: "public(parent)",
            Visibility.PRIVATE: "private",
        }.get(visibility, "private")

    def _error(self, kind: ErrorKind, message: str, line: int, column: int,
               hint: Optional[str] = None, source_file: Optional[str] = None):
        """Report an error with automatic source file detection.

        If source_file is not provided, attempts to determine it from the
        current method or function context.
        """
        if source_file is None:
            source_file = self._get_current_source_file()
        self.reporter.error(kind, message, line, column, hint, source_file)

    def _warning(self, kind: ErrorKind, message: str, line: int, column: int,
                 hint: Optional[str] = None, source_file: Optional[str] = None):
        """Report a warning with automatic source file detection."""
        if source_file is None:
            source_file = self._get_current_source_file()
        self.reporter.warning(kind, message, line, column, hint, source_file)

    def _validate_exports(self, program: Program):
        """`export` statements are only permitted in init.saw facade files.

        Applied on every compile path (single-file and per-module), so a stray
        `export` in a regular file is diagnosed regardless of whether the file
        also uses imports/modules.
        """
        exports = getattr(program, 'exports', [])
        if not exports:
            return
        source_path = getattr(program, 'source_path', None)
        if source_path is None:
            # Provenance unknown (e.g. an imported module AST that was not tagged
            # with its path); the entry file always carries source_path, so this
            # only skips imported modules — matching prior per-module behavior.
            return
        if source_path.endswith('init.saw'):
            return
        for exp in exports:
            self.reporter.error(
                ErrorKind.SYNTAX,
                "`export` statements are only allowed in init.saw files",
                exp.line, exp.column,
                hint="use `public` visibility modifier to expose symbols from regular modules"
            )

    def check(self, program: Program, require_main: bool = True) -> bool:
        """Type check the entire program. Returns True if no errors.

        Args:
            program: The AST to type check
            require_main: If True, error if no main() function (default for executables).
                         Set to False for library/object file compilation.
        """
        # Validate: exports are only allowed in init.saw files
        self._validate_exports(program)

        # First pass: register type definitions (aliases)
        for type_def in program.type_definitions:
            self._register_type_definition(type_def)

        # Second pass: collect struct definitions
        for struct in program.structs:
            self._register_struct(struct)

        # Third pass: collect enum definitions
        for enum in program.enums:
            self._register_enum(enum)

        # Fourth pass: collect trait definitions
        for trait in program.traits:
            self._register_trait(trait)

        # Fifth pass: register extensions and their methods. The structural
        # `deinit` (design 128) is synthesized first, as a whole-program
        # pre-pass, so registration sees it like any hand-written one.
        self._synthesize_implicit_deinits(program)
        for extension in program.extensions:
            self._register_extension(extension)

        # Fifth-a.5 pass: validate `any Trait` existentials in all declared
        # signatures/fields (design 51 object safety + unsized discipline). Runs
        # after traits are registered so object safety is decidable.
        self._validate_existentials_in_program(program)

        # Same pass over the same positions for the `unsafe` effect on written
        # function TYPES (design 136): present exactly when the signature names
        # an unsafe type. Runs after struct registration, which is what makes an
        # `unsafe struct` recognizable.
        self._validate_fn_effects_in_program(program)

        # Fifth-b pass: check resource management containment rules
        self._check_no_copy_containment()
        self._check_implicit_copy_containment()
        self._check_explicit_copy_containment()
        self._check_enum_policy_declared()
        self._check_copy_trait_exclusivity()
        self._check_derivable_copy()
        self._check_derivable_equals()
        self._check_derivable_compare()
        self._check_derivable_hash()
        self._check_ord_hash_require_equatable()

        # Register extern functions (FFI)
        for extern_block in program.extern_blocks:
            for extern_func in extern_block.functions:
                self._register_extern_function(extern_func)

        # Sixth pass: collect function signatures
        for func in program.functions:
            self._register_function(func)

        # Sixth-b pass: register module-level statics (design 41). After
        # structs/enums/functions so a const initializer may reference them.
        for static in getattr(program, 'statics', []):
            self._register_static(static)

        # Overloading (design 55): now that every function/method signature is
        # registered, assign each member of a 2+ overload set its type-signature
        # codegen symbol (stamped on both the symbol and its AST node).
        self._stamp_overload_symbols()

        # design 58: validate @export / @section on functions and statics.
        self._check_attribute_semantics(program)

        # Check for main function (only required for executables)
        if require_main and not self.namespace.has_function("main"):
            self.reporter.error(
                ErrorKind.UNDEFINED_FUNCTION,
                "no `main` function found",
                1, 1,
                hint="add a `func main() { }` function as the entry point, or use -c to compile as object file"
            )

        # Seventh pass: type check function bodies
        for func in program.functions:
            self._check_function(func)

        # Eighth pass: type check method bodies
        for extension in program.extensions:
            self._check_extension(extension)

        # design 53: type-check top-level static_assert conditions (stamps the
        # annotations the codegen const evaluator consumes; surfaces type errors).
        for sa in getattr(program, 'static_asserts', []):
            self._check_static_assert(sa)

        # Ninth pass: whole-program `sync` effect analysis (design 22).
        self.finalize_effects()

        return not self.reporter.has_errors()

    # ------------------------------------------------------------------ design 58
    # C-export signature whitelist. Function parameters accept these scalar
    # kinds; the return additionally accepts Void and Never (noreturn). Everything
    # else — Bool, String, Optional, Result/enum, tuple, closure, by-value struct,
    # array, existential, reference — is rejected (pass UnsafePointer<S> for an
    # aggregate). Bool is REJECTED in v1: the extern-import path lowers it as a
    # bare `i1`, which does not match the platform C `_Bool` ABI, and no stdlib
    # extern actually passes a Bool, so there is no sound precedent to mirror.
    _EXPORT_FN_SCALAR_KINDS = frozenset({
        TypeKind.INT, TypeKind.UINT,
        TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
        TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64,
        TypeKind.FLOAT, TypeKind.POINTER,
    })
    # Exported STATIC data has no calling convention, so the whitelist relaxes to
    # scalars (no pointer — a static pointer to nothing is not meaningful data),
    # plus arrays and structs recursively built from whitelisted fields.
    _EXPORT_STATIC_SCALAR_KINDS = frozenset({
        TypeKind.INT, TypeKind.UINT,
        TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
        TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64,
        TypeKind.FLOAT,
    })

    def _describe_type_for_export(self, t: SawType) -> str:
        """Short human phrase for a non-whitelisted export type."""
        resolved = self._resolve_type_alias(t)
        k = resolved.kind
        phrases = {
            TypeKind.BOOL: "`Bool`",
            TypeKind.STRING: "`String`",
            TypeKind.OPTIONAL: "an optional (`T?`)",
            TypeKind.TUPLE: "a tuple",
            TypeKind.FUNCTION: "a closure",
            TypeKind.ARRAY: "an array",
            TypeKind.STRUCT: f"the by-value struct `{resolved.struct_name}`",
            TypeKind.ENUM: f"the enum `{resolved.enum_name}`",
            TypeKind.EXISTENTIAL: "an `any` existential",
            TypeKind.REFERENCE: "a reference",
        }
        return phrases.get(k, f"`{k.name}`")

    def _export_fn_type_ok(self, t: SawType, *, is_return: bool) -> bool:
        resolved = self._resolve_type_alias(t)
        k = resolved.kind
        if k in self._EXPORT_FN_SCALAR_KINDS:
            return True
        if is_return and k in (TypeKind.VOID, TypeKind.NEVER):
            return True
        return False

    def _export_static_type_ok(self, t: SawType, _seen=None) -> bool:
        resolved = self._resolve_type_alias(t)
        k = resolved.kind
        if k in self._EXPORT_STATIC_SCALAR_KINDS:
            return True
        if k == TypeKind.ARRAY:
            return self._export_static_type_ok(resolved.array_element_type)
        if k == TypeKind.STRUCT:
            # Recurse into fields; guard against cyclic struct graphs.
            seen = _seen or set()
            if resolved.struct_name in seen:
                return True
            seen = seen | {resolved.struct_name}
            info = self.get_struct_info(resolved.struct_name)
            if info is None or getattr(info, 'type_params', None):
                return False  # unknown or generic struct: not a fixed C layout
            for _fname, ftype in info.fields.items():
                if not self._export_static_type_ok(ftype, seen):
                    return False
            return True
        return False

    def _register_export_symbol(self, sym: str, node) -> None:
        """Symbol hygiene (design 58): reserved-symbol collision + duplicate
        exported-symbol detection across the whole compilation unit."""
        src = getattr(node, 'source_file', None)
        if sym == "main" or sym.startswith("saw_") or sym.startswith("__saw_"):
            # Runtime-build mode (design 113b): a runtime AUTHORED IN SAW exports
            # the frozen `__saw_rt_*` ABI (sawc/rt/ABI.md). Allow exactly those
            # names here; a non-ABI `__saw_rt_*` export is a typo (the accepted
            # set is named), and every other reserved name stays rejected even in
            # this mode — a runtime must not hijack `main`/`saw_*`/the `__saw_*`
            # compiler-internal helpers.
            from runtime_abi import RUNTIME_ABI_SYMBOLS, valid_export_names_message
            if getattr(self, 'runtime_build', False) and sym in RUNTIME_ABI_SYMBOLS:
                pass  # a valid runtime-ABI export
            elif getattr(self, 'runtime_build', False) and sym.startswith("__saw_rt_"):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`@export` symbol `{sym}` is not part of the frozen "
                    f"`__saw_rt_*` runtime ABI",
                    node.line, node.column,
                    hint="under `--runtime-build` only the frozen ABI names may "
                         "be exported; valid names are: "
                         f"{valid_export_names_message()}",
                    source_file=src)
                return
            else:
                hint = ("choose a different exported symbol name via "
                        "`@export(\"other_name\")`")
                if sym.startswith("__saw_rt_"):
                    hint = ("`__saw_rt_*` names are the runtime ABI — a runtime "
                            "authored in Saw exports them under `--runtime-build`; "
                            "an ordinary program must choose a different name")
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`@export` symbol `{sym}` collides with a reserved runtime "
                    f"symbol (`main`, `saw_*`, `__saw_*`)",
                    node.line, node.column,
                    hint=hint,
                    source_file=src)
                return
        prev = self._export_symbol_table.get(sym)
        if prev is not None:
            pname, pline, _pcol, _pfile = prev
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"duplicate `@export` symbol `{sym}` (already exported by "
                f"`{pname}` at line {pline})",
                node.line, node.column,
                hint="an unmangled C symbol must be unique across the program; "
                     "give one an explicit `@export(\"other_name\")`",
                source_file=src)
            return
        self._export_symbol_table[sym] = (
            getattr(node, 'name', sym), node.line, node.column, src)

    def _check_attribute_semantics(self, program: Program) -> None:
        """design 58 Part 2/3: validate @export and @section semantics on the
        functions and statics of one module (parser already enforced grammar +
        position). Suspension-freedom of an exported function is checked by the
        effect machinery, which treats it as a `sync` root (see effects.py)."""
        from ast_nodes import is_exported, export_symbol, section_name

        for func in program.functions:
            sec = section_name(func)
            if sec is not None and sec.strip() == "":
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    "`@section` name must be a non-empty string",
                    func.line, func.column, source_file=func.source_file)
            if not is_exported(func):
                continue
            sym = export_symbol(func)
            if func.type_params:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot `@export` the generic function `{func.name}` — a C "
                    f"symbol has no type parameters",
                    func.line, func.column,
                    hint="export a concrete, non-generic wrapper instead",
                    source_file=func.source_file)
            for p in func.parameters:
                if not self._export_fn_type_ok(p.type, is_return=False):
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`@export` function `{func.name}`: parameter `{p.name}` "
                        f"has type {self._describe_type_for_export(p.type)}, "
                        f"which is not C-ABI-safe",
                        func.line, func.column,
                        hint="exported signatures allow fixed-width integers, "
                             "Int/UInt, Float, and UnsafePointer<T>; pass an "
                             "aggregate by `UnsafePointer<S>`",
                        source_file=func.source_file)
            if not self._export_fn_type_ok(func.return_type, is_return=True):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`@export` function `{func.name}`: return type "
                    f"{self._describe_type_for_export(func.return_type)} is not "
                    f"C-ABI-safe",
                    func.line, func.column,
                    hint="exported returns allow fixed-width integers, Int/UInt, "
                         "Float, UnsafePointer<T>, Void, or Never (noreturn)",
                    source_file=func.source_file)
            self._register_export_symbol(sym, func)

        for static in getattr(program, 'statics', []):
            sec = section_name(static)
            if sec is not None and sec.strip() == "":
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    "`@section` name must be a non-empty string",
                    static.line, static.column, source_file=static.source_file)
            if not is_exported(static):
                continue
            sym = export_symbol(static)
            if not self._export_static_type_ok(static.type):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`@export` static `{static.name}`: type "
                    f"{self._describe_type_for_export(static.type)} is not a "
                    f"C-ABI-safe data layout",
                    static.line, static.column,
                    hint="exported statics allow fixed-width integers, Int/UInt, "
                         "Float, arrays thereof, and structs of such fields",
                    source_file=static.source_file)
            self._register_export_symbol(sym, static)

    def check_module(
        self,
        module_ast: Program,
        module_path: Tuple[str, ...],
        checked_modules: Dict[Tuple[str, ...], Tuple[Program, 'Namespace']],
        builtin_namespace: 'Namespace',
        parent_namespace: Optional['Namespace'] = None,
        is_entry: bool = False
    ) -> Optional['Namespace']:
        """
        Type check a single module with its own namespace.

        This implements per-module type checking where each module is type-checked
        in isolation with only its imports visible. This is the Phase 5.0 approach.

        Args:
            module_ast: The parsed Program AST for this module
            module_path: The module's path as a tuple (e.g., ("std", "io"))
            checked_modules: Dict of already type-checked modules (path -> (ast, namespace))
            builtin_namespace: Pre-populated namespace with builtins
            parent_namespace: Optional parent module's namespace for nested modules
            is_entry: True if this is the entry module (should check for main)

        Returns:
            The module's namespace if successful, None on error
        """
        from namespace import (
            Namespace, FunctionSymbol, StructSymbol, EnumSymbol,
            TraitSymbol, TypeAliasSymbol, TraitMethodSymbol
        )
        from ast_nodes import Visibility

        # Create a fresh namespace for this module
        ns = Namespace(module_path=module_path)
        ns.package_root = builtin_namespace.package_root

        # Clone builtins into this module's namespace (all directly accessible)
        ns.merge_into(builtin_namespace)
        ns.directly_accessible = set(builtin_namespace.directly_accessible)

        # Inherit from parent if this is a nested module
        if parent_namespace:
            # Design 144: bind the parent's types under the names they are
            # written as, mapping to their identities — never under the
            # identity itself, which is not a spelling any source can use.
            for name, _ident, sym in parent_namespace.iter_structs():
                if sym.visibility == Visibility.PUBLIC:
                    ns.register_struct(name, sym)
                    ns.make_accessible(name)
            for name, _ident, sym in parent_namespace.iter_enums():
                if sym.visibility == Visibility.PUBLIC:
                    ns.register_enum(name, sym)
                    ns.make_accessible(name)
            for name, sym in parent_namespace.functions.items():
                if sym.visibility == Visibility.PUBLIC:
                    if name not in ns.functions:
                        ns.register_function(name, sym)
                    ns.make_accessible(name)
            for name, _ident, sym in parent_namespace.iter_traits():
                if sym.visibility == Visibility.PUBLIC:
                    ns.register_trait(name, sym)
                    ns.make_accessible(name)

        # When an import copies a public struct/enum symbol into THIS namespace
        # (glob `import foo.*` or specific `import foo.{A}`), carry its trait
        # conformances along too. Without this, a containment/conformance query
        # in the importing module (e.g. "does DepList implement NoCopy?") sees the
        # copied struct but not its NoCopy conformance and wrongly errors — the
        # glob path does not register the source module in `ns.modules`, so
        # `type_conforms_to`'s cross-module walk cannot reach it either.
        def _import_conformances(dst_name, src_name, src_ns):
            src_map = src_ns.conformances.get(src_name)
            if not src_map:
                return
            dst_map = ns.conformances.setdefault(dst_name, {})
            for trait_name, assoc in src_map.items():
                dst_map.setdefault(trait_name, assoc)

        # Design 142: the defining modules this file DIRECTLY imports, collected
        # as the import list is processed. Extension-method lookup consults
        # exactly these (plus the current module and the receiver's own), so a
        # transitive dependency injects nothing.
        direct_imports: Set[Tuple[str, ...]] = set()

        # Process imports - register imported modules in this namespace
        for imp in getattr(module_ast, 'imports', []):
            imp_path = tuple(imp.path)
            # Handle package/parent prefixes
            if imp_path and imp_path[0] == 'package':
                imp_path = imp_path[1:]
            elif imp_path and imp_path[0] == 'parent':
                # Resolve relative to current module
                if len(module_path) > 0:
                    imp_path = module_path[:-1] + imp_path[1:]
                else:
                    imp_path = imp_path[1:]

            # design 82 Part B: `import std.<module>[.{A, B} | .*]` is a PRELUDE
            # import — the std symbols already live in the builtin namespace
            # (merged into `ns`); the import just makes the requested names
            # accessible (non-prelude std is compiler-known but not auto-visible).
            if imp.path and imp.path[0] == 'std':
                std_leaf = self._process_std_import(imp, ns, builtin_namespace)
                if std_leaf is not None:
                    direct_imports.add(("<std>", std_leaf))
                continue

            if imp.is_glob:
                # import foo.* -> copy all public symbols to local namespace
                base_path = imp_path[:-1] if imp_path and imp_path[-1] == '*' else imp_path
                direct_imports.add(base_path)
                if base_path in checked_modules:
                    source_ast, source_ns = checked_modules[base_path]
                    glob_label = '.'.join(base_path) if base_path else "<entry>"
                    for name, ident, sym in source_ns.iter_structs():
                        if sym.visibility == Visibility.PUBLIC:
                            ns.register_struct(name, sym, source_label=glob_label)
                            ns.make_accessible(name)
                            _import_conformances(ident, ident, source_ns)
                    for name, ident, sym in source_ns.iter_enums():
                        if sym.visibility == Visibility.PUBLIC:
                            ns.register_enum(name, sym, source_label=glob_label)
                            ns.make_accessible(name)
                            _import_conformances(ident, ident, source_ns)
                    for name, sym in source_ns.functions.items():
                        if sym.visibility == Visibility.PUBLIC:
                            if name not in ns.functions:
                                ns.register_function(name, sym)
                            ns.make_accessible(name)
                    for name, _ident, sym in source_ns.iter_traits():
                        if sym.visibility == Visibility.PUBLIC:
                            ns.register_trait(name, sym, source_label=glob_label)
                            ns.make_accessible(name)
                    for name, sym in source_ns.statics.items():
                        if sym.visibility == Visibility.PUBLIC:
                            if name not in ns.statics:
                                ns.register_static(name, sym)
                            ns.make_accessible(name)
            elif imp.symbols:
                # import foo.{A, B} -> copy specific symbols to local namespace
                direct_imports.add(imp_path)
                if imp_path in checked_modules:
                    _, source_ns = checked_modules[imp_path]
                    aliases = imp.symbol_aliases or {}
                    for sym_name in imp.symbols:
                        # design 53: a `Name as Local` import binds the symbol
                        # under `Local` in this namespace — a pure local rename
                        # (the symbol object, and thus its mangling, is unchanged).
                        local = aliases.get(sym_name, sym_name)
                        # Copy the symbol from source to local namespace
                        sel_label = ('.'.join(imp_path) if imp_path
                                     else "<entry>")
                        sel_struct = source_ns.lookup_struct(sym_name)
                        sel_enum = (None if sel_struct is not None
                                    else source_ns.lookup_enum(sym_name))
                        if sel_struct is not None:
                            sym = sel_struct
                            if sym.visibility == Visibility.PUBLIC:
                                ns.register_struct(local, sym,
                                                   source_label=sel_label)
                                ns.make_accessible(local)
                                _ident = source_ns.resolve_type_identity(sym_name)
                                _import_conformances(_ident, _ident, source_ns)
                        elif sel_enum is not None:
                            sym = sel_enum
                            if sym.visibility == Visibility.PUBLIC:
                                ns.register_enum(local, sym,
                                                 source_label=sel_label)
                                ns.make_accessible(local)
                                _ident = source_ns.resolve_type_identity(sym_name)
                                _import_conformances(_ident, _ident, source_ns)
                        elif sym_name in source_ns.functions:
                            sym = source_ns.functions[sym_name]
                            if sym.visibility == Visibility.PUBLIC:
                                # For an ALIASED function, bind a copy whose
                                # codegen name is the real symbol (design 53), so
                                # a call under the alias reaches the real
                                # definition. Unaliased imports are unchanged.
                                if local != sym_name and not sym.mangled_name:
                                    import dataclasses
                                    sym = dataclasses.replace(
                                        sym, mangled_name=sym_name)
                                if local not in ns.functions:
                                    ns.register_function(local, sym)
                                ns.make_accessible(local)
                        elif sym_name in source_ns.statics:
                            sym = source_ns.statics[sym_name]
                            if sym.visibility == Visibility.PUBLIC:
                                if local not in ns.statics:
                                    ns.register_static(local, sym)
                                ns.make_accessible(local)
                        elif source_ns.lookup_trait(sym_name) is not None:
                            sym = source_ns.lookup_trait(sym_name)
                            if sym.visibility == Visibility.PUBLIC:
                                ns.register_trait(local, sym,
                                                  source_label=sel_label)
                                ns.make_accessible(local)
                    # Also register module for qualified access to non-imported symbols
                    alias = imp.path[-1] if imp.path else ""
                    from namespace import ModuleSymbol
                    ns.modules[alias] = ModuleSymbol(
                        namespace=source_ns,
                        path=list(imp_path),
                        visibility=Visibility.PRIVATE
                    )
            else:
                # import foo.bar -> register module for qualified access
                direct_imports.add(imp_path)
                if imp_path in checked_modules:
                    alias = imp.alias or (imp.path[-1] if imp.path else "")
                    _, source_ns = checked_modules[imp_path]
                    from namespace import ModuleSymbol
                    ns.modules[alias] = ModuleSymbol(
                        namespace=source_ns,
                        path=list(imp_path),
                        visibility=Visibility.PRIVATE  # Imports are private
                    )

        # Handle external module declarations (`module foo`)
        # These are registered for qualified access just like imports
        for mod_decl in getattr(module_ast, 'module_decls', []):
            if not mod_decl.is_inline:
                # External module declaration
                mod_path = (mod_decl.name,)
                direct_imports.add(mod_path)
                if mod_path in checked_modules:
                    _, source_ns = checked_modules[mod_path]
                    from namespace import ModuleSymbol
                    mod_visibility = Visibility.PUBLIC if mod_decl.is_public else Visibility.PRIVATE
                    ns.modules[mod_decl.name] = ModuleSymbol(
                        namespace=source_ns,
                        path=list(mod_path),
                        visibility=mod_visibility
                    )

        # Register this module's own declarations

        # Save old state
        old_namespace = self.namespace
        old_module_path = self.current_module_path
        old_direct_imports = self.current_direct_imports
        self.namespace = ns
        self.current_module_path = module_path
        self.current_direct_imports = direct_imports

        # Validate: exports are only allowed in init.saw files (same rule as the
        # single-file path; enforced here so the unified pipeline still catches
        # a stray `export` in a regular entry/module file).
        self._validate_exports(module_ast)

        # Register type definitions
        for type_def in module_ast.type_definitions:
            self._register_type_definition(type_def)
            ns.make_accessible(type_def.name)

        # Register structs
        for struct in module_ast.structs:
            self._register_struct(struct)
            ns.make_accessible(struct.name)

        # Register enums
        for enum in module_ast.enums:
            self._register_enum(enum)
            ns.make_accessible(enum.name)

        # Register traits
        for trait in module_ast.traits:
            self._register_trait(trait)
            ns.make_accessible(trait.name)

        # Design 144: this module's types are all registered now, so its
        # name -> identity view is complete. Rewrite every type REFERENCE in the
        # module — field types, signatures, annotations — to the identity it
        # denotes, before extension registration or any body check reads one.
        self._canonicalize_module_types(module_ast)

        # Register extensions (structural `deinit` synthesized first, design 128)
        self._synthesize_implicit_deinits(module_ast)
        for extension in module_ast.extensions:
            self._register_extension(extension)

        # Validate `any Trait` existentials in declared signatures (design 51),
        # and the `unsafe` effect on written function types (design 136).
        self._validate_existentials_in_program(module_ast)
        self._validate_fn_effects_in_program(module_ast)

        # Check resource containment rules
        self._check_no_copy_containment()
        self._check_implicit_copy_containment()
        self._check_explicit_copy_containment()
        self._check_enum_policy_declared()
        self._check_copy_trait_exclusivity()
        self._check_derivable_copy()
        self._check_derivable_equals()
        self._check_derivable_compare()
        self._check_derivable_hash()
        self._check_ord_hash_require_equatable()

        # Register extern functions
        for extern_block in module_ast.extern_blocks:
            for extern_func in extern_block.functions:
                self._register_extern_function(extern_func)
                ns.make_accessible(extern_func.name)

        # Register functions
        for func in module_ast.functions:
            self._register_function(func)
            ns.make_accessible(func.name)

        # Register module-level statics (design 41). Accessible module-locally;
        # a `public` static is additionally visible to importers.
        for static in getattr(module_ast, 'statics', []):
            self._register_static(static)
            ns.make_accessible(static.name)

        # Handle inline module declarations BEFORE type-checking function bodies
        # This ensures that inline modules are available for use in the current module
        for mod_decl in getattr(module_ast, 'module_decls', []):
            if mod_decl.is_inline and mod_decl.body:
                inline_path = module_path + (mod_decl.name,)
                inline_ns = self.check_module(
                    mod_decl.body,
                    inline_path,
                    checked_modules,
                    builtin_namespace,
                    parent_namespace=ns,
                    is_entry=False
                )
                if inline_ns is None:
                    # Error in inline module
                    self.namespace = old_namespace
                    self.current_module_path = old_module_path
                    self.current_direct_imports = old_direct_imports
                    return None

                # Register the inline module in this module's namespace
                from namespace import ModuleSymbol
                mod_visibility = Visibility.PUBLIC if mod_decl.is_public else Visibility.PRIVATE
                ns.modules[mod_decl.name] = ModuleSymbol(
                    namespace=inline_ns,
                    path=list(inline_path),
                    visibility=mod_visibility
                )

        # Overloading (design 55): stamp overload-set codegen symbols for this
        # module now that all its signatures are registered.
        self._stamp_overload_symbols()

        # DF-140f: give this module's PRIVATE free functions a module-local
        # codegen symbol, so a same-named private function in another module is
        # a different definition rather than an "ambiguous function" report.
        self._stamp_module_private_functions()

        # design 58: validate @export / @section on this module's functions and
        # statics. The export-symbol table accumulates across every module the
        # shared checker visits, so a duplicate exported C symbol across modules
        # in the same compilation unit is caught.
        self._check_attribute_semantics(module_ast)

        # Check for main function (only for entry module)
        if is_entry and not self.namespace.has_function("main"):
            self.reporter.error(
                ErrorKind.UNDEFINED_FUNCTION,
                "no `main` function found",
                1, 1,
                hint="add a `func main() { }` function as the entry point, or use -c to compile as object file"
            )

        # Enable import checking for this module
        ns.enable_import_checking()

        # design 70 (A5): snapshot pristine (pre-body-check) copies of every
        # generic function template, so a suspending instantiation can be cloned +
        # substituted + re-checked for per-instantiation effect inference.
        import copy as _copy
        for func in module_ast.functions:
            if getattr(func, 'type_params', None) and not getattr(
                    func, 'is_mono_instance', False):
                # Design 105: a generic OVERLOAD carries a distinct `$OL$` base
                # symbol; key its pristine template by that so two overloads of one
                # name don't collide (a lone generic keeps its plain-name key).
                key = getattr(func, 'mangled_symbol', None) or func.name
                self._pristine_generics[key] = _copy.deepcopy(func)
        # Method-level generic methods on a NON-generic extension: pristine snapshot
        # keyed by (struct, method), with the owning extension (design 70).
        for ext in module_ast.extensions:
            if getattr(ext, 'type_params', None):
                # design 74 (A5-rest, shape 2): an extension on a GENERIC struct
                # (`extension Holder<T>`). Snapshot every method (not just
                # method-level generics): driving `__saw_drive(b.run())` for a concrete
                # receiver `Holder<Int>` monomorphizes the method over the STRUCT's
                # type params so the coroutine frame's `__recv` gets a concrete
                # layout. Keyed by (struct, method); the ext carries the struct's
                # type params for substitution.
                for m in ext.methods:
                    if not getattr(m, 'is_mono_instance', False):
                        self._pristine_generic_struct_methods[
                            (ext.struct_name, m.name)] = (_copy.deepcopy(m), ext)
                continue
            for m in ext.methods:
                if getattr(m, 'type_params', None) and not getattr(
                        m, 'is_mono_instance', False):
                    self._pristine_generic_methods[(ext.struct_name, m.name)] = (
                        _copy.deepcopy(m), ext)

        # Type check function bodies
        for func in module_ast.functions:
            self._check_function(func)

        # Type check method bodies
        for extension in module_ast.extensions:
            self._check_extension(extension)

        # design 70 (A5): build + re-check every queued generic instantiation so
        # its effect node (keyed by the mangled symbol) is populated before the
        # whole-program fixpoint. Splices concrete clones into `module_ast`, which
        # the coroutine transform and codegen then treat as ordinary functions.
        if is_entry:
            self._process_effect_monos(module_ast)
            # design 74 (A5-rest, shape 3): stash the entry module namespace so the
            # coroutine transform can splice + re-check a nested-generic
            # instantiation post-fixpoint with the SAME symbol scope the body checks
            # used (the namespace is restored below before the transform runs).
            self._entry_module_ns = ns
            self._entry_module_path = self.current_module_path

        # design 53: walk top-level static_assert conditions so their annotations
        # (Int.max limit tag, sizeof type args) are stamped for codegen.
        for sa in getattr(module_ast, 'static_asserts', []):
            self._check_static_assert(sa)

        # Restore old state
        self.namespace = old_namespace
        self.current_module_path = old_module_path
        self.current_direct_imports = old_direct_imports

        # Whole-program `sync` effect analysis (design 22). The entry module is
        # checked last, after every other module's bodies have contributed their
        # call-graph edges, so this runs once over the complete graph.
        if is_entry:
            self.finalize_effects()

        if self.reporter.has_errors():
            return None

        return ns

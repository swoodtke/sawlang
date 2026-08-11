"""
Saw Language Type Checker
Performs type checking and semantic analysis on the AST.
"""

import itertools
from contextlib import contextmanager
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
from target_info import platform_int_width, has_native_atomics
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
from .serde import SerdeMixin


_BINDING_ID_COUNTER = itertools.count(1)


def _module_source_files(module_ast):
    """Every distinct source file the declarations of `module_ast` came from.

    A module is a DIRECTORY (design 82 makes each std file its own module, and a
    user module can span several `.saw` files), so "which module owns this
    declaration" is answered per file rather than per AST. Design 210 unit 4
    keys a module's checked scope on this so a generic template can be re-checked
    where it was written.
    """
    seen = []
    for group in ('functions', 'structs', 'enums', 'extensions', 'traits',
                  'statics', 'type_aliases'):
        for decl in getattr(module_ast, group, None) or ():
            src = getattr(decl, 'source_file', None)
            if src and src not in seen:
                seen.append(src)
    return seen


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
    # design 75 (A2): this binding was initialized as a MULTI-THREADED group
    # (`TaskGroup(threads: N)`), so a later `group.spawn(...)` into it turns on
    # the Send-on-frames gate. The default `TaskGroup()` — and every other
    # construction — leaves it False and the gate skipped.
    is_mt_group: bool = False


@dataclass
class TaskCaptureBorrow:
    """One reference borrow registered at a `group.spawn(...)` (design 189, and
    design 201 for the argument position).

    A reference into a spawned task borrows its ROOT for the task's life, and the
    task's HANDLE carries that borrow: joining the handle releases it, and a
    handle that is discarded or never joined releases at the GROUP's death.
    The record is what makes that extent visible to the Law of Exclusivity —
    it is a new extent, not a new checker.

    Both spellings produce the same record — a `[&var x]` CAPTURE (design 189)
    and a `&var x` ARGUMENT of the spawned call (design 201) — because they are
    the same extent. `kind` exists so a diagnostic can name what the author
    wrote; nothing about the rule reads it.
    """
    root_id: int                       # VariableInfo.binding_id of the root
    root_name: str
    mutable: bool                      # `&var x` exclusive vs `&x` shared
    spawn_line: int
    spawn_column: int
    kind: str = 'capture'              # 'capture' | 'argument' — wording only
    group_id: Optional[int] = None     # the group binding the task was spawned into
    group_name: Optional[str] = None
    handle_id: Optional[int] = None    # the binding the `TaskHandle` landed in
    handle_name: Optional[str] = None
    # Lines this borrow has already been reported against, so one statement
    # that both reads and writes a root yields one diagnostic rather than a
    # pile (the receiver of `buf.push(9)` is checked twice on the way down).
    reported: set = field(default_factory=set)


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


class TypeChecker(ExpressionsMixin, StatementsMixin, RegistrationMixin, TypeUtilsMixin, EffectsMixin, PlacesMixin, SerdeMixin):
    """Type checks a Saw program."""

    def __init__(self, reporter: ErrorReporter, freestanding: bool = False,
                 runtime_build: bool = False, post_transform: bool = False,
                 no_hidden_alloc: bool = False,
                 target_triple: Optional[str] = None,
                 target_features: Optional[str] = None,
                 runtime_provider: bool = False):
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
        # design 149 unit d: `SpinLock` is a CAS loop, so it needs the target to
        # HAVE a compare-and-swap. Where the backend expands one into `__atomic_*`
        # libcalls (rv32i and friends) the type is refused with a teaching error
        # rather than compiled into a lock that calls into a C runtime a kernel
        # does not have. Computed once — on every ordinary target it is True and
        # the check below costs a boolean test per expression.
        self._atomics_native = has_native_atomics(target_triple, target_features)
        self._spinlock_refused = False
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
        # design 149 unit c: `[package] runtime = true` — this PACKAGE is a
        # runtime provider. Same export permission as `--runtime-build`, and the
        # same sync-only discipline (an `@export` function is a sync root), but
        # it is an ordinary package build: std is loaded, and the output links.
        # What it adds is the check nothing did before — an exported seam's
        # signature against the contract in rt/ABI.md.
        self.runtime_provider = runtime_provider
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
        # design 189: the reference captures spawned tasks are holding RIGHT
        # HERE. Function-local like the move state above, and conservative at
        # every join point — a borrow released on only one branch comes back at
        # the end of the branch, because the other path never joined.
        self._task_borrows: List['TaskCaptureBorrow'] = []
        # The borrows the spawn in the statement being checked just opened,
        # waiting for the `let h = ...` binding that will carry them. Cleared at
        # every statement boundary, so nothing else can claim them.
        self._pending_task_borrows: List['TaskCaptureBorrow'] = []
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
        # Structs/enums whose serialize()/deserialize() are compiler-derived
        # (design 169). Unlike the sets above these carry a real synthesized
        # BODY, filled by `_synthesize_serde_bodies` once every type is
        # registered — the field walk needs a nested type's conformance and an
        # enum's raw backing, neither of which is known while the extension that
        # triggers the derivation is being registered.
        self._derived_serialize_types: set[str] = set()
        self._derived_deserialize_types: set[str] = set()
        # Body-unique counter for the names a synthesized serde body binds.
        self._serde_tmp: int = 0
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

        # --- wired in from outside, declared here (design 194 unit 1) --------
        # These two are handed over by the driver rather than built here, and
        # were runtime grafts until the graft gate went in. Declaring them is
        # what makes the reader sites' `getattr(self, ..., {})` a fact about the
        # PHASE (not yet wired) instead of a fact about the object's shape.
        #
        # design 82/150: std symbol -> the std FILE that defines it, filled by
        # `sawc.py` once the builtin namespace has been built. The import gate
        # asks it whether a bare std name needs an import.
        self._std_symbol_file: Dict[str, str] = {}
        # design 45: the suspending METHODS the effect fixpoint settled on,
        # handed back by the coroutine transform for its own second pass.
        self._suspending_methods_set: Optional[set] = None

        # design 204: the source file of the declaration currently being
        # REGISTERED, for `_type_lookup_module`. Registration resolves a
        # signature before any body is entered, so the current-function path
        # cannot answer there; `_declaring` maintains this.
        self._decl_source_file: Optional[str] = None

        # design 210 unit 4: source FILE -> the (module path, namespace) that
        # file's declarations were checked under, filled by `check_module` as
        # each module finishes. Read by `_home_module_scope`, which is how a
        # GENERIC instantiation gets re-checked where its template was written
        # instead of where the call that reached it was.
        self._module_scope_by_file: Dict[str, Tuple[Tuple[str, ...], Any]] = {}
        # …and the design-142 direct imports each module was checked with, which
        # `Namespace` does not carry. Same lifetime, same reader.
        self._direct_imports_by_module: Dict[Tuple[str, ...], Set[Tuple[str, ...]]] = {}

        # design 194 unit 4: the prelude-gate reports already made, keyed by
        # (module, name, line, column). The front half re-enters the same AST
        # (place lowering, the coroutine transform's re-check), so a rule that
        # fires per resolution would print each diagnostic more than once.
        self._gate_reported: set = set()

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

    # ------------------------------------------------------------------ #
    # THE PRIVATE-TYPE-NAME LOOKUP MODULE — the funnel (design 204,
    # obligation 1).
    #
    # A std file's PRIVATE type name lives in that file's own view
    # (`Namespace.module_type_names`) and nowhere else, so a lookup by bare
    # name has to say WHO is looking. One decision procedure, this one, and it
    # answers with the module of the source file the name was written in.
    #
    # ENTRY POINTS — every place a bare type name is turned into a symbol or an
    # identity:
    #   * `_canonical_type_name` (typechecker/types.py) — the name -> identity
    #     canonicalizer, itself the chokepoint `_resolve_type`, extension
    #     registration and `_canonicalize_module_types` go through.
    #   * `get_struct_info` / `get_enum_info` / `get_trait_info` /
    #     `get_type_alias_info` (typechecker/types.py) — the four symbol
    #     lookups; an expression-position name (`State.Unset`,
    #     `MapSlot.Occupied(...)`) reaches a private std type only here.
    # Codegen is deliberately NOT an entry point: everything downstream of type
    # checking holds identities (design 144's central invariant), so it looks
    # its types up by key and never asks this question.
    #
    # WHERE THE ANSWER COMES FROM, in order:
    #   1. `_decl_source_file` — the declaration being REGISTERED. Registration
    #      resolves signatures and alias right-hand sides before any body is
    #      entered, so `current_function`/`current_method` are still empty.
    #   2. the current function/method's source file — every body check.
    #   3. `current_module_path` — the fallback `_vis_module_for_source` gives
    #      a file it cannot place, which is the user-module answer.
    # ------------------------------------------------------------------ #
    def _type_lookup_module(self) -> Tuple[str, ...]:
        """The module whose FILE-PRIVATE type names are in scope right now."""
        src = self._decl_source_file or self._get_current_source_file()
        return self._vis_module_for_source(src)

    @contextmanager
    def _declaring(self, decl):
        """Register/check `decl` with its own source file in force, so a bare
        name in its signature resolves against ITS module's private types."""
        saved = self._decl_source_file
        self._decl_source_file = getattr(decl, 'source_file', None) or saved
        try:
            yield
        finally:
            self._decl_source_file = saved

    def _lend_instantiation_types(self, src_ns, dst_ns, type_map):
        """Make the concrete TYPE ARGUMENTS of an instantiation resolvable in the
        template's home namespace — the "plus the instantiation map" half of
        design 210's generic path.

        A template's home scope has its own private siblings and none of the
        caller's types. That is exactly backwards for one thing and exactly right
        for everything else: `amplify<Lo>`'s body names `boost` (home) AND `Lo`
        (the caller's), and `w.seed()` cannot be resolved without the `extension
        Lo: Seed` the caller wrote. So the type arguments — and only they — are
        lent across.

        Additive and non-clobbering: a name the home module already binds keeps
        its own meaning, so this can never change what the template itself means.
        The entries stay after the recheck, which is harmless because the home
        module's own declarations were all checked before any instantiation of
        it could be built.
        """
        if not type_map or src_ns is None or dst_ns is None or src_ns is dst_ns:
            return
        seen = set()

        def lend(t, depth=0):
            if t is None or depth > 6:
                return
            for name in (getattr(t, 'struct_name', None),
                         getattr(t, 'enum_name', None)):
                if not name or name in seen:
                    continue
                seen.add(name)
                if name in src_ns.structs and name not in dst_ns.structs:
                    dst_ns.structs[name] = src_ns.structs[name]
                if name in src_ns.enums and name not in dst_ns.enums:
                    dst_ns.enums[name] = src_ns.enums[name]
                if name in src_ns.conformances and name not in dst_ns.conformances:
                    dst_ns.conformances[name] = src_ns.conformances[name]
                if name in src_ns.generic_structs and name not in dst_ns.generic_structs:
                    dst_ns.generic_structs[name] = src_ns.generic_structs[name]
            for written, identity in list(src_ns.type_names.items()):
                if identity in seen and written not in dst_ns.type_names:
                    dst_ns.type_names[written] = identity
            for child in ((getattr(t, 'type_args', None) or [])
                          + (getattr(t, 'element_types', None) or [])):
                lend(child, depth + 1)
            lend(getattr(t, 'inner_type', None), depth + 1)

        for arg in type_map.values():
            lend(arg)

    @contextmanager
    def _home_module_scope(self, decl, type_map=None):
        """Check `decl` under the scope of the module that DECLARED it.

        Design 210 unit 4 — the generic path. A generic body cannot be embedded
        from its declaration-time annotations alone: designs 70/74 re-infer both
        types and EFFECTS per instantiation, because both depend on the type
        arguments. So the recheck stays; what moves is where it runs. A template
        in `embedmod` calling `embedmod`'s private `boost` must be re-checked
        with `embedmod`'s namespace installed, not with the namespace of
        whichever module reached the template — under which `boost` is not a
        name, the recheck silently resolves nothing (its errors are suppressed:
        it is an annotation harvest), and the clone comes out with untyped
        locals that surface much later as `local `b` in driven `amplify$1$Lo`
        has no resolved type` (DF-206e's generic costume).

        Composes with design 204's `_type_lookup_module` rather than duplicating
        it: this installs the SYMBOL scope (functions, statics, variables) while
        `_declaring` installs the TYPE-name scope, and both key off the same
        thing — the declaration's own `source_file`.

        ENTRY POINTS — every per-instantiation recheck (process rule 1):
          * `_build_fn_mono` — a queued generic free-function instantiation
          * `_splice_fn_mono` — the post-fixpoint splice the coroutine transform
            asks for when it promotes a nested suspending generic call
          * `_build_method_mono` — a method-generic instantiation
          * `_build_generic_struct_method_mono` — a driven method on a generic
            struct (design 74 shape 2)

        A declaration whose file was never recorded — a single-file compile, a
        std template, a synthesized clone with no source — falls back to the
        current scope, which is what every one of these did before.
        """
        src = getattr(decl, 'source_file', None)
        entry = self._module_scope_by_file.get(src) if src else None
        if entry is None:
            with self._declaring(decl):
                yield
            return
        home_path, home_ns = entry
        saved_ns = self.namespace
        saved_path = self.current_module_path
        saved_imports = self.current_direct_imports
        # The instantiation map: the caller's concrete type arguments, lent into
        # the template's scope so `w.seed()` finds the caller's conformance.
        self._lend_instantiation_types(saved_ns, home_ns, type_map)
        self.namespace = home_ns
        self.current_module_path = home_path
        # Design 142: extension lookup reads the DIRECT imports of the file being
        # checked, so a template that reaches an extension of its own dep keeps
        # reaching it. `Namespace` does not carry them, so they are re-derived
        # from the module the template belongs to.
        self.current_direct_imports = self._direct_imports_by_module.get(
            home_path, saved_imports)
        try:
            with self._declaring(decl):
                yield
        finally:
            self.namespace = saved_ns
            self.current_module_path = saved_path
            self.current_direct_imports = saved_imports

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

    _SPINLOCK_NAME = "SpinLock"

    def _check_spinlock_target(self, t, node) -> None:
        """Refuse `SpinLock` on a target with no real atomics (design 149 unit d).

        A spinlock IS its compare-and-swap loop. Where the backend has no atomic
        instruction to lower that to, it emits `__atomic_compare_exchange` — a
        call into a C runtime a freestanding kernel does not have, and which,
        where it exists, is usually itself implemented with a lock. Either way
        the type would not be what it says it is, so this is a teaching error
        naming the flag rather than a silent fallback. Reported once per compile:
        the fix is one flag, not one edit per use site.
        """
        if self._atomics_native or self._spinlock_refused or t is None:
            return
        # std checks itself under its own typechecker; refusing the type there
        # would anchor the diagnostic in `std/spinlock.saw` rather than at the
        # use site, and report it as a builtin failure on top. The user's own
        # check reaches every `SpinLock` they actually named.
        if getattr(self, '_checking_builtins', False):
            return
        if not self._type_names_spinlock(t):
            return
        self._spinlock_refused = True
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"`SpinLock` needs target atomics, and `{self.target_triple}` has "
            f"none: its base ISA omits the `A` extension, so a "
            f"compare-and-swap lowers to an `__atomic_*` libcall",
            getattr(node, 'line', 0), getattr(node, 'column', 0),
            hint="enable the extension: `--target-features +a`. Without it the "
                 "lock would call into a C runtime a freestanding target does "
                 "not have, and which is usually itself implemented with a "
                 "lock; for state a single core serializes by construction, "
                 "reach for `unsafe static var` instead",
            source_file=getattr(node, 'source_file', None) or None,
        )

    def _type_names_spinlock(self, t) -> bool:
        """Whether `t`'s own tree names a `SpinLock` (walked like the unsafe
        tree: through optionals, references, arrays, tuples and type args)."""
        if t is None:
            return False
        if t.kind == TypeKind.STRUCT and t.struct_name == self._SPINLOCK_NAME:
            return True
        for sub in (getattr(t, 'inner_type', None),
                    getattr(t, 'array_element_type', None),
                    getattr(t, 'func_return_type', None)):
            if self._type_names_spinlock(sub):
                return True
        for group in ('type_args', 'element_types', 'param_types'):
            for sub in (getattr(t, group, None) or []):
                if self._type_names_spinlock(sub):
                    return True
        return False

    def _note_unsafe_static_contact(self, name: str, node) -> None:
        """Record that the function being checked NAMED an `unsafe static var`
        (design 149 unit a).

        The trigger rule is otherwise about types, and the type of a mutable
        static is usually an ordinary safe one — `[HandleSlot; 64]` says nothing
        about who may write it. What is unsafe is the DECLARATION: its
        consistency rests on a serialization argument no signature carries. So
        naming one is contact, and every function that touches it is declared
        `unsafe` and reviewed, which is the whole enforcement story for compound
        global state.
        """
        if self._unsafe_contact is not None:
            return
        self._unsafe_contact = (getattr(node, 'line', 0),
                                getattr(node, 'column', 0),
                                "its body names an unsafe static", name)

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

    def _module_qualifier(self, name):
        """The module `name` denotes as a qualifier HERE, or None (design 150
        pin 4).

        Qualifier bindings are WEAK. Resolution runs local scopes -> module-level
        declarations -> imported bare names -> qualifiers, so a local, parameter
        or capture called `data` simply wins, with no shadowing error, and the
        shadow is LEXICAL: in the next function `data.` reaches the module again.
        std leaves are among the most natural local names in the language
        (`data`, `path`, `time`, `net`), and binding one as a qualifier may not
        cost the author the name — that was design 82's whole reason for not
        creating the alias in the first place."""
        if not name:
            return None
        scope = getattr(self, 'current_scope', None)
        if scope is not None and scope.lookup(name) is not None:
            return None
        ns = self.namespace
        if name in ns.directly_accessible:
            return None
        return ns.modules.get(name)

    def _shadowed_qualifier(self, name):
        """The module a declaration of `name` would shadow, or None. Feeds both
        the `-W shadowed-qualifier` warning and the member-lookup diagnostic."""
        if not name:
            return None
        return self.namespace.modules.get(name)

    def _warn_shadowed_qualifier(self, name, line, column):
        """`-W shadowed-qualifier` (design 150 section 4b), the language's first
        warning category. Emitted where a binding TAKES the name of a visible
        module qualifier — the declaration, not the later use that trips over
        it. Off unless the flag asks for it; the use-site error is what fires
        unconditionally."""
        if getattr(self, '_checking_builtins', False):
            return
        if self.post_transform or self._in_synthesized_context():
            return
        module_sym = self._shadowed_qualifier(name)
        if module_sym is None:
            return
        path = '.'.join(getattr(module_sym, 'path', ()) or ()) or name
        self._warning(
            ErrorKind.DUPLICATE_VARIABLE,
            f"`{name}` shadows the module qualifier bound by `import {path}`",
            line, column,
            hint=f"qualified access is unavailable while this binding is in "
                 f"scope — rename it, or write `import {path} as <name>`",
            category="shadowed-qualifier")

    def _qualifier_shadow_hint(self, obj, member):
        """Design 150 pin 4's diagnostic contract.

        When member lookup fails on a value whose NAME also binds a module
        qualifier, the author almost certainly meant the module — `data.Data()`
        under a local `data`. Say which declaration took the name and give the
        three ways out. Returns the hint text, or None when this is an ordinary
        missing member."""
        from ast_nodes import Identifier
        if not isinstance(obj, Identifier):
            return None
        module_sym = self._shadowed_qualifier(obj.name)
        if module_sym is None:
            return None
        scope = getattr(self, 'current_scope', None)
        info = scope.lookup(obj.name) if scope is not None else None
        if info is None:
            return None
        path = '.'.join(getattr(module_sym, 'path', ()) or ()) or obj.name
        return (f"`{obj.name}` here is the binding declared on line {info.line}, "
                f"which shadows the module qualifier bound by `import {path}` — "
                f"rename the binding, import the module as another name "
                f"(`import {path} as <name>`), or select `{member}` directly "
                f"(`import {path}.{{{member}}}`)")

    def _bind_module_qualifier(self, ns, imp, alias, path, source_ns):
        """Bind `alias` as a module qualifier in `ns` (design 150 pins 1, 3, 5).

        One import form or another, a qualifier is one name bound to one module.
        Two imports claiming it is reported HERE, at the import, naming both
        paths — the use site could only say the qualifier reached the wrong
        module, which is the wrong place to learn it."""
        from namespace import ModuleSymbol
        prior = ns.modules.get(alias)
        if prior is not None and list(getattr(prior, 'path', ())) != list(path):
            self._error(
                ErrorKind.DUPLICATE_IMPORT,
                f"two imports bind the qualifier `{alias}`: "
                f"`{'.'.join(prior.path)}` and `{'.'.join(path)}`",
                getattr(imp, 'line', 0), getattr(imp, 'column', 0),
                hint=f"rename one with `as`, e.g. "
                     f"`import {'.'.join(path)} as <name>`")
            return
        ns.modules[alias] = ModuleSymbol(
            namespace=source_ns, path=list(path),
            visibility=Visibility.PRIVATE,  # an import is never re-exported
        )

    def _std_leaf_namespace(self, leaf, builtin_namespace):
        """The namespace `import std.<leaf>` binds its qualifier to (design 150).

        A per-FILE view over the already-checked builtin namespace, holding the
        leaf's own top-level declarations and sharing every symbol object with
        it — so `time.Instant` and an `import std.time.{Instant}` name one type,
        with one identity and one mangling. Built once per leaf per compile."""
        from namespace import StdLeafNamespace
        cache = getattr(self, '_std_leaf_ns_cache', None)
        if cache is None:
            cache = {}
            self._std_leaf_ns_cache = cache
        view = cache.get(leaf)
        if view is not None:
            return view

        file_symbols = getattr(builtin_namespace, '_std_file_symbols', {}) or {}
        view = StdLeafNamespace(module_path=("<std>", leaf))
        for name in sorted(file_symbols.get(leaf, ())):
            for lookup, register in (
                (builtin_namespace.lookup_struct, view.register_struct),
                (builtin_namespace.lookup_enum, view.register_enum),
                (builtin_namespace.lookup_trait, view.register_trait),
                (builtin_namespace.lookup_type_alias, view.register_type_alias),
            ):
                sym = lookup(name)
                if sym is not None:
                    register(name, sym)
                    # Carry the type's conformances so a query made through the
                    # qualifier (does `time.Duration` implement Comparable?)
                    # answers the same as one made through a bare import.
                    ident = builtin_namespace.resolve_type_identity(name)
                    conf = builtin_namespace.conformances.get(ident)
                    if conf:
                        view.conformances.setdefault(ident, dict(conf))
                    break
            else:
                fn = builtin_namespace.functions.get(name)
                if fn is not None:
                    view.register_function(name, fn)
                    overloads = builtin_namespace.lookup_function_overloads(name)
                    if len(overloads) > 1:
                        view.function_overloads[name] = list(overloads)
            view.make_accessible(name)
        cache[leaf] = view
        return view

    def _process_std_import(self, imp, ns, builtin_namespace) -> Optional[str]:
        """Bind an `import std.<module>` into the importing namespace.

        Design 150: std goes through the SAME three forms as a user module, and
        the design-82 Part B special case (whole-module std bare-exposes) is
        gone. `import std.time` binds the qualifier `time` and exposes nothing
        bare; `import std.time.*` exposes every name of the module bare;
        `import std.time.{Instant}` exposes the named ones bare AND binds the
        qualifier for reaching the rest.

        The symbols themselves already live in `builtin_namespace` and are
        merged into `ns`, so bare exposure is a matter of un-gating a name
        (design 82's accessibility set) rather than copying a symbol.

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

        is_glob = bool(getattr(imp, 'is_glob', False)) or list(imp.path)[-1:] == ['*']

        if imp.symbols:
            aliases = imp.symbol_aliases or {}
            for sym_name in imp.symbols:
                if sym_name not in available:
                    # A name std HAS, in another file, is the interesting case:
                    # say where it moved to instead of listing what is here. A
                    # prelude owner is worth naming as such — the fix is to
                    # DELETE the import, which no list of alternatives suggests.
                    owner = getattr(builtin_namespace, '_std_symbol_file',
                                    {}).get(sym_name)
                    required = getattr(builtin_namespace,
                                       '_import_required_modules', set())
                    if owner is not None and owner != leaf and owner in required:
                        hint = (f"it is in `std.{owner}` — write "
                                f"`import std.{owner}.{{{sym_name}}}`")
                    elif owner is not None and owner != leaf:
                        hint = ("it is in the prelude and needs no import — "
                                "drop it from this list")
                    else:
                        hint = "available: " + ", ".join(sorted(available))
                    self._error(
                        ErrorKind.UNKNOWN_TYPE,
                        f"`{sym_name}` is not defined in `std.{leaf}`",
                        getattr(imp, 'line', 0), getattr(imp, 'column', 0),
                        hint=hint)
                    continue
                _expose(sym_name, aliases.get(sym_name, sym_name))
        elif is_glob:
            # `import std.X.*` — the explicit bare opt-in (design 150 pin 2).
            for sym_name in available:
                _expose(sym_name, sym_name)

        # Design 150 pins 1 and 3: the whole-module and selective forms bind the
        # last path segment as a qualifier (`as Y` overrides). The glob form does
        # not, exactly as a user-module glob does not — it gave you the names.
        if not is_glob:
            self._bind_module_qualifier(
                ns, imp,
                alias=getattr(imp, 'alias', None) or leaf,
                path=["std", leaf],
                source_ns=self._std_leaf_namespace(leaf, builtin_namespace))
        return leaf

    def _decl_is_std_sourced(self, node) -> bool:
        """Whether a declaration comes from a std/builtin source file."""
        sf = getattr(node, 'source_file', None)
        if not sf:
            return False
        return self._vis_module_for_source(sf)[:1] == ("<std>",)

    def _decl_is_foreign_splice(self, node) -> bool:
        """Whether this declaration's body was written in a DIFFERENT module
        from the one now checking it — i.e. the coroutine transform spliced it
        here.

        Design 210 unit 5, and this is where design 84's std-only special case
        dissolves. 84 built cross-module embedding for std methods and gave the
        spliced body a permission — check it with the accessibility gate off,
        "like the builtin check" — on the reasoning that the gate judges user
        SOURCE and a spliced body is not source at this position. That
        reasoning was never about std. It is about the SPLICE, and it is just as
        true of a user module: `builder.Builder.build` embedded into blade's
        `main` is exactly as much "not source here" as `TcpListener.accept` is.
        std got the permission because std was the only module design 84 could
        embed; DF-206e is what the other kind of module got instead.

        So the predicate is provenance, not privilege. Most of what the
        permission used to cover is gone — a spliced body's namespace-consulting
        nodes carry `embed_preserved` and are never re-resolved (unit 3) — and
        what remains is the positions no `resolved_type` ever reaches, above all
        a module-private `static` named in a CONST position (`[UInt32;
        RESOLVE_MAX]`, `[0; RESOLVE_MAX]`), which is resolved as a name every
        time it is seen. Those keep the permission, and now they keep it
        wherever the body came from.
        """
        sf = getattr(node, 'source_file', None)
        if not sf:
            return False
        if self._vis_module_for_source(sf)[:1] == ("<std>",):
            return True
        entry = self._module_scope_by_file.get(sf)
        return entry is not None and entry[0] != self.current_module_path

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
        # Design 150: name all three forms. A whole-module `import std.file` no
        # longer exposes `File` bare — it binds the qualifier — so a hint that
        # offered only that spelling would send the reader in a circle.
        self._error(
            ErrorKind.UNKNOWN_TYPE,
            f"`{name}` is not in the prelude and must be imported",
            line, column,
            hint=f"`import std.{owner}.{{{name}}}` selects it, "
                 f"`import std.{owner}.*` takes the module's whole vocabulary "
                 f"bare, and `import std.{owner}` lets you write "
                 f"`{owner}.{name}`",
        )
        return True

    # THE PRELUDE GATE OVER A WRITTEN TYPE — the funnel (design 194 unit 4,
    # closing DF-188k and DF-193d).
    #
    # `_std_name_gated` fires in EXPRESSION positions — a call, a struct
    # literal, a static-method head — which reaches a gated type only where a
    # VALUE of it is built. A signature that merely RECEIVES one builds nothing,
    # so `func take(d: &Data) -> Int` compiled with no `import std.data`
    # (DF-188k). Design 188 unit 7 hand-walked the one position where the
    # consequence was an ICE (a `static`'s annotation); design 193 unit 7 tried
    # to generalize it and BACKED OUT, because the author's spelling is gone by
    # the time any check runs — `_canonicalize_module_types` rewrites
    # `struct_name` to the design-144 identity and `_register_function`'s
    # design-68 write-back replaces the annotation object, after which a legal
    # qualified `data.Data` reads exactly like a bare unimported `Data`.
    #
    # `SawType.written_name` is that missing record, stamped by the parser at
    # the one place a named type is built. So the rule is: gate what the AUTHOR
    # WROTE, never what the compiler resolved it to.
    #
    # ENTRY POINTS (obligation 1 — a funnel names its entries). One decision
    # procedure, `_gate_resolved_type`, reached from FOUR places:
    #   * `_resolve_type` (typechecker/types.py) — the funnel proper. Every
    #     annotation that is RESOLVED passes through it: a parameter, a return
    #     type, a `let x: T`, a `static`'s type, a type argument, a referent, an
    #     array element, a tuple element, a function type's parts, an `any
    #     Trait` erasure.
    #   * `_register_struct` — a struct FIELD's type is stored raw and read
    #     straight off the AST by the field checks and by codegen, so it never
    #     reaches resolution as a unit.
    #   * `_register_enum` — an enum PAYLOAD's type, for the same reason.
    #   * `_register_type_alias` — a `type R = T` right-hand side, likewise.
    # The last three are declaration slots the compiler deliberately does not
    # resolve eagerly (a generic struct's `T`-typed field has nothing to resolve
    # against yet); they call the same walk with the same rule, so there is one
    # answer to "is this name gated", not four.
    #
    # Design 188 unit 7's separate `static` mini-walk is RETIRED here: the
    # funnel covers that position now, and keeping both printed the diagnostic
    # twice — once at the declaration, once at the annotation.
    #
    # FIVE EXEMPTIONS, each an over-rejection the census warned about:
    #   * no `written_name` -- the compiler built this type. Every internal
    #     caller that resolves a std-derived type while checking a user body is
    #     covered by this one, which is the whole point of provenance.
    #   * a qualified spelling (`data.Data`) -- the qualifier only exists
    #     because an import bound it; gating it would refuse the legal form.
    #   * `_checking_builtins` -- std's own bodies name std types by
    #     construction.
    #   * `post_transform` -- the re-check after the coroutine transform reads
    #     an AST whose synthesized frames hold std types in fields.
    #   * `_in_synthesized_context` -- compiler-generated declarations.
    def _gate_written_type(self, written, depth: int = 0) -> None:
        """Run the prelude gate over every node of a WRITTEN type.

        The walk is needed because `_resolve_type` does not recurse into every
        composite it accepts — `UnsafePointer<T>` has no resolution arm at all —
        so a per-node check at the funnel's head would miss what the funnel
        itself never visits.
        """
        if written is None or depth > 8:
            return
        if self._gate_exempt():
            return
        self._gate_resolved_type(written)
        for child in (written.inner_type, written.array_element_type,
                      written.func_return_type):
            self._gate_written_type(child, depth + 1)
        for child in ((written.type_args or []) + (written.element_types or [])
                      + (written.param_types or [])):
            self._gate_written_type(child, depth + 1)

    def _gate_exempt(self) -> bool:
        """The three whole-pass exemptions the prelude gate honours."""
        return bool(getattr(self, '_checking_builtins', False)
                    or getattr(self, 'post_transform', False)
                    or self._in_synthesized_context())

    def _gate_resolved_type(self, saw_type) -> None:
        """Gate a type ARRIVING AT RESOLUTION, on its own written provenance.

        Anchors each report where the author wrote the NAME rather than at the
        enclosing declaration, and reports a given name-at-a-position once: the
        front half re-enters the same AST several times (the place lowering, the
        coroutine transform's re-check), and a rule that fires per resolution
        would print the same diagnostic three times.
        """
        name = saw_type.written_name
        if not name or '.' in name:
            return
        if self._gate_exempt():
            return
        # std's own declarations are REGISTERED inside a user compile — an
        # `import std.file.*` carries std.file's signatures along, and those name
        # `Path` bare because std files extend each other by design (design 82).
        # The gate is about what a USER wrote, so it reads the file the spelling
        # came from, exactly as `_decl_is_std_sourced` does for member access.
        if self._vis_module_for_source(saw_type.written_file)[:1] == ("<std>",):
            return
        key = (saw_type.written_file, name,
               saw_type.written_line, saw_type.written_column)
        if key in self._gate_reported:
            return
        self._gate_reported.add(key)
        self._std_name_gated(name, saw_type.written_line,
                             saw_type.written_column)

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
                 hint: Optional[str] = None, source_file: Optional[str] = None,
                 category: Optional[str] = None):
        """Report a warning with automatic source file detection. A `category`
        names a `-W` opt-in (design 150); without one the warning is
        unconditional."""
        if source_file is None:
            source_file = self._get_current_source_file()
        self.reporter.warning(kind, message, line, column, hint, source_file,
                              category=category)

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

        # design 148: const VALUE parameters are checked and their defaults
        # folded before anything reads a type-parameter list.
        self._resolve_const_params_in_program(program)

        # DF-172j: same position, same reason. A `static` may be an array
        # length, so the constant a name denotes has to be known before the
        # struct pass below resolves the first `[UInt8; REGION_SIZE]` field —
        # four passes earlier than statics are registered.
        self._collect_const_statics(program)
        self._fold_const_lengths_in_program(program)

        # First pass: register type definitions (aliases)
        for type_def in program.type_definitions:
            with self._declaring(type_def):
                self._register_type_definition(type_def)

        # Second pass: collect struct definitions
        for struct in program.structs:
            with self._declaring(struct):
                self._register_struct(struct)

        # Third pass: collect enum definitions
        for enum in program.enums:
            with self._declaring(enum):
                self._register_enum(enum)

        # Fourth pass: collect trait definitions
        for trait in program.traits:
            with self._declaring(trait):
                self._register_trait(trait)

        # DF-172j second half: a bare-name const generic ARGUMENT that is a
        # `static` (`FixedBuf<CAP>`). Needs the referenced type's parameter list
        # to tell a const argument from a type one, so it runs here — after
        # structs and enums are registered, before anything takes a type's
        # identity from its arguments.
        self._fold_const_type_args_in_program(program)

        # design 185 unit 3: lengths again, now that enums exist. A length may
        # name a raw-backed enum's case (`[UInt8; Perm.Read | Perm.Write]`), and
        # a case has no value until the enum is registered — which is two passes
        # after the first fold. Folding is idempotent (only a length that is
        # still unresolved is touched) and it mutates the same type objects the
        # struct symbols hold, so a FIELD written that way lands too.
        self._fold_const_lengths_in_program(program)

        # Design 144: this unit's types are all registered now, so the
        # name -> identity view is complete. Rewrite every type REFERENCE to
        # the identity it denotes, before extension registration or any body
        # check reads one. `check_module` does the same at the same seam; this
        # is the single-file path AND the builtins, where design 204 makes the
        # rewrite load-bearing (a std file's private type name means something
        # different in each file, and the whole-program passes below read
        # signatures with no file in hand).
        self._canonicalize_module_types(program)

        # Fifth pass: register extensions and their methods. The structural
        # `deinit` (design 128) is synthesized first, as a whole-program
        # pre-pass, so registration sees it like any hand-written one.
        self._synthesize_implicit_deinits(program)
        for extension in program.extensions:
            with self._declaring(extension):
                self._register_extension(extension)

        # Fifth-a.5 pass: validate `any Trait` existentials in all declared
        # signatures/fields (design 51 object safety + unsized discipline). Runs
        # after traits are registered so object safety is decidable.
        self._validate_existentials_in_program(program)

        # Same pass, same positions (design 188 unit 1): the design-163 no-escape
        # walk re-run with type ALIASES RESOLVED. The written-form checks live in
        # the parser, where no alias can be looked up yet, so `type R = &Int` was
        # a bypass for every position they guard.
        self._validate_no_ref_laundering_in_program(program)

        # Same position, same reason (design 148): every type-parameter BOUND
        # names a trait. Traits are registered by now, so a forward reference
        # resolves and a non-trait is diagnosable at the declaration.
        self._validate_type_param_bounds_in_program(program)

        # Same pass over the same positions for the `unsafe` effect on written
        # function TYPES (design 136): present exactly when the signature names
        # an unsafe type. Runs after struct registration, which is what makes an
        # `unsafe struct` recognizable.
        self._validate_fn_effects_in_program(program)

        # Fifth-b pass: check resource management containment rules
        self._check_no_copy_containment()
        self._check_no_move_declarations()
        self._check_implicit_copy_containment()
        self._check_explicit_copy_containment()
        self._check_enum_policy_declared()
        self._check_copy_trait_exclusivity()
        self._check_derivable_copy()
        self._check_derivable_equals()
        self._check_derivable_compare()
        self._check_derivable_hash()
        self._check_ord_hash_require_equatable()

        # design 169: fill in the bodies of derived serialize/deserialize. Here
        # rather than at registration because the field walk reads a nested
        # type's conformance and an enum's raw backing, and before body checking
        # because what it builds is ordinary source the checker then sees.
        self._synthesize_serde_bodies(program)

        # Register extern functions (FFI)
        for extern_block in program.extern_blocks:
            for extern_func in extern_block.functions:
                with self._declaring(extern_func):
                    self._register_extern_function(extern_func)

        # Sixth pass: collect function signatures
        for func in program.functions:
            with self._declaring(func):
                self._register_function(func)

        # Sixth-b pass: register module-level statics (design 41). After
        # structs/enums/functions so a const initializer may reference them.
        for static in getattr(program, 'statics', []):
            with self._declaring(static):
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
            with self._declaring(sa):
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

    def _check_blocking_extern_signature(self, extern_func) -> None:
        """design 183 unit 2: an `extern blocking func`'s signature must be one
        the offload thunk can marshal.

        That set is exactly the one `@export` already admits, for the same
        reason: the offload hands the extern's arguments to a worker thread and
        the thread makes a plain C call with them. Design 103 v1 allowed only
        `(Int) -> Int` — one machine word in, one out — which could not express
        a single annotation the design-181 audit recommended (a child wait's
        three-argument pipe drain, a resolver's `(host, out, max)`). The check
        runs at the DECLARATION, like `@export`'s, so an unmarshallable extern
        is refused where it is written rather than at whichever call site the
        transform happened to reach first.
        """
        for p in extern_func.parameters:
            ptype = self._resolve_type(p.type)
            if not self._export_fn_type_ok(ptype, is_return=False):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`extern blocking func {extern_func.name}`: parameter "
                    f"`{p.name}` has type "
                    f"{self._describe_type_for_export(ptype)}, which is not "
                    f"C-ABI-safe",
                    extern_func.line, extern_func.column,
                    hint="an offloaded signature allows fixed-width integers, "
                         "Int/UInt, Float, and UnsafePointer<T>; pass an "
                         "aggregate by `UnsafePointer<S>`, and keep what it "
                         "points at in frame-owned or heap storage so it "
                         "outlives the park",
                    source_file=getattr(extern_func, 'source_file', None))
        rtype = self._resolve_type(extern_func.return_type)
        if not self._export_fn_type_ok(rtype, is_return=True):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`extern blocking func {extern_func.name}`: return type "
                f"{self._describe_type_for_export(rtype)} is not C-ABI-safe",
                extern_func.line, extern_func.column,
                hint="an offloaded return allows fixed-width integers, "
                     "Int/UInt, Float, UnsafePointer<T>, Void, or Never "
                     "(noreturn) — one value, marshalled back through the job",
                source_file=getattr(extern_func, 'source_file', None))

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

    # Saw type -> the machine class the C ABI distinguishes, matching
    # `runtime_abi._ABI_CLASSES`. Pointers and platform Int/UInt are all
    # pointer-width and share a class; the fixed-width kinds are their own,
    # because that is where a mismatch changes what crosses the boundary.
    _ABI_CLASS_BY_KIND = {
        TypeKind.VOID: "void",
        TypeKind.NEVER: "noreturn",
        TypeKind.INT: "word",
        TypeKind.UINT: "word",
        TypeKind.POINTER: "word",
        TypeKind.INT64: "i64",
        TypeKind.UINT64: "i64",
        TypeKind.INT32: "i32",
        TypeKind.UINT32: "i32",
        TypeKind.INT16: "i16",
        TypeKind.UINT16: "i16",
        TypeKind.INT8: "i8",
        TypeKind.UINT8: "i8",
        TypeKind.FLOAT: "float",
    }

    def _saw_abi_class(self, t: SawType) -> str:
        resolved = self._resolve_type_alias(t) if t is not None else None
        if resolved is None:
            return "void"
        return self._ABI_CLASS_BY_KIND.get(resolved.kind, resolved.kind.name.lower())

    def _check_runtime_abi_signature(self, sym: str, func) -> None:
        """Check an exported seam against rt/ABI.md's signature (design 149 c).

        The `__saw_rt_*` boundary exists to be stable, and until now nothing
        checked an implementation against the document that freezes it: a seam
        written with the wrong arity, or returning a `word` where the ABI says
        `Int64`, linked cleanly and went wrong at run time on a 32-bit target.
        The document is read directly, so it cannot drift from what is enforced.

        Width and arity are what is checked. Pointer-versus-integer is not a
        distinction the C ABI makes at this width, and ABI.md itself spells the
        same handle `ptr` in one place and `word` in another, so treating them
        as different would report differences that are not.
        """
        from runtime_abi import abi_signatures, render_abi_signature
        expected = abi_signatures().get(sym)
        if expected is None:
            return  # not described by the document — nothing to check against
        want_params, want_ret = expected
        got_params = tuple(self._saw_abi_class(p.type) for p in func.parameters)
        got_ret = self._saw_abi_class(func.return_type)
        if got_params == want_params and got_ret == want_ret:
            return
        got = f"{sym}({', '.join(got_params)}) -> {got_ret}"
        if len(got_params) != len(want_params):
            detail = (f"it takes {len(got_params)} parameter(s) where the ABI "
                      f"takes {len(want_params)}")
        elif got_ret != want_ret:
            detail = f"it returns `{got_ret}` where the ABI returns `{want_ret}`"
        else:
            i = next(n for n, (a, b) in enumerate(zip(got_params, want_params))
                     if a != b)
            detail = (f"parameter {i + 1} is `{got_params[i]}` where the ABI "
                      f"takes `{want_params[i]}`")
        self.reporter.error(
            ErrorKind.TYPE_MISMATCH,
            f"`@export` seam `{sym}` does not match the runtime ABI: {detail}",
            func.line, func.column,
            hint=f"sawc/rt/ABI.md freezes this contract as "
                 f"`{render_abi_signature(sym)}`; this one is `{got}`. A runtime "
                 f"is a link-time swap, so a seam that disagrees with the "
                 f"document links cleanly and misbehaves at run time",
            source_file=getattr(func, 'source_file', None))

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
            # design 149 unit c: a package that DECLARES itself a runtime
            # provider (`[package] runtime = true`) exports the seams on the same
            # terms as a `--runtime-build` compile of `sawc/rt/`. Both are a
            # runtime; only one of them is ours.
            runtime_role = (getattr(self, 'runtime_build', False)
                            or getattr(self, 'runtime_provider', False))
            if runtime_role and sym in RUNTIME_ABI_SYMBOLS:
                pass  # a valid runtime-ABI export
            elif runtime_role and sym.startswith("__saw_rt_"):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`@export` symbol `{sym}` is not part of the frozen "
                    f"`__saw_rt_*` runtime ABI",
                    node.line, node.column,
                    hint="a runtime may export only the frozen ABI names; "
                         "valid names are: "
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
            # design 149 unit c: a seam's signature is checked against the
            # document that freezes it, for a runtime built either way.
            if sym.startswith("__saw_rt_") and (
                    getattr(self, 'runtime_build', False)
                    or getattr(self, 'runtime_provider', False)):
                self._check_runtime_abi_signature(sym, func)

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
        is_entry: bool = False,
        require_main: Optional[bool] = None
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
            is_entry: True if this is the LAST module of the compilation unit —
                the one after which the whole-program work runs (design 70's
                queued generic instantiations, then the design-22 effect
                fixpoint). It is a fact about POSITION in the graph, not about
                the output shape.
            require_main: True if the program must define `main`. Defaults to
                `is_entry`. DF-158e: these two were one flag, so `-c` /
                `--freestanding` (which have no `main` to require) also skipped
                the effect fixpoint — leaving every callee's `suspends` bit
                False, so the coroutine transform's closure walk never reached a
                spawn root's nested suspending callees and the call lowered as a
                direct BLOCKING one. In a kernel the nested park then runs
                inline. An object file is still a whole program's worth of
                effect graph; only the entry-point requirement differs.

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
                    # The selective form ALSO binds the qualifier, for reaching
                    # the names it did not select (design 150 pin 3).
                    self._bind_module_qualifier(
                        ns, imp,
                        alias=(imp.alias or (imp.path[-1] if imp.path else "")),
                        path=list(imp_path), source_ns=source_ns)
            else:
                # import foo.bar -> register module for qualified access
                direct_imports.add(imp_path)
                if imp_path in checked_modules:
                    _, source_ns = checked_modules[imp_path]
                    self._bind_module_qualifier(
                        ns, imp,
                        alias=(imp.alias or (imp.path[-1] if imp.path else "")),
                        path=list(imp_path), source_ns=source_ns)

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

        # design 148: const VALUE parameters, before any type-param list is read.
        self._resolve_const_params_in_program(module_ast)

        # DF-172j: this module's const-foldable statics, before the struct pass
        # resolves a field whose length names one.
        self._collect_const_statics(module_ast)
        self._fold_const_lengths_in_program(module_ast)

        # Register type definitions
        for type_def in module_ast.type_definitions:
            with self._declaring(type_def):
                self._register_type_definition(type_def)
            ns.make_accessible(type_def.name)

        # Register structs
        for struct in module_ast.structs:
            with self._declaring(struct):
                self._register_struct(struct)
            ns.make_accessible(struct.name)

        # Register enums
        for enum in module_ast.enums:
            with self._declaring(enum):
                self._register_enum(enum)
            ns.make_accessible(enum.name)

        # Register traits
        for trait in module_ast.traits:
            with self._declaring(trait):
                self._register_trait(trait)
            ns.make_accessible(trait.name)

        # DF-172j second half: a bare-name const generic ARGUMENT that is a
        # `static`, now that the referenced types' parameter lists exist.
        self._fold_const_type_args_in_program(module_ast)

        # design 185 unit 3: and lengths again, now that this module's enums are
        # registered — a raw-backed case is a constant only once it has one.
        self._fold_const_lengths_in_program(module_ast)

        # Design 144: this module's types are all registered now, so its
        # name -> identity view is complete. Rewrite every type REFERENCE in the
        # module — field types, signatures, annotations — to the identity it
        # denotes, before extension registration or any body check reads one.
        self._canonicalize_module_types(module_ast)

        # Register extensions (structural `deinit` synthesized first, design 128)
        self._synthesize_implicit_deinits(module_ast)
        for extension in module_ast.extensions:
            with self._declaring(extension):
                self._register_extension(extension)

        # Validate `any Trait` existentials in declared signatures (design 51),
        # type-parameter bounds (design 148), and the `unsafe` effect on written
        # function types (design 136).
        self._validate_existentials_in_program(module_ast)
        self._validate_type_param_bounds_in_program(module_ast)
        self._validate_fn_effects_in_program(module_ast)
        # design 188 unit 1: the no-escape walk again, with aliases resolved.
        self._validate_no_ref_laundering_in_program(module_ast)

        # Check resource containment rules
        self._check_no_copy_containment()
        self._check_no_move_declarations()
        self._check_implicit_copy_containment()
        self._check_explicit_copy_containment()
        self._check_enum_policy_declared()
        self._check_copy_trait_exclusivity()
        self._check_derivable_copy()
        self._check_derivable_equals()
        self._check_derivable_compare()
        self._check_derivable_hash()
        self._check_ord_hash_require_equatable()

        # design 169: fill in the bodies of derived serialize/deserialize. Here
        # rather than at registration because the field walk reads a nested
        # type's conformance and an enum's raw backing, and before body checking
        # because what it builds is ordinary source the checker then sees.
        self._synthesize_serde_bodies(module_ast)

        # Register extern functions
        for extern_block in module_ast.extern_blocks:
            for extern_func in extern_block.functions:
                with self._declaring(extern_func):
                    self._register_extern_function(extern_func)
                ns.make_accessible(extern_func.name)

        # Register functions
        for func in module_ast.functions:
            with self._declaring(func):
                self._register_function(func)
            ns.make_accessible(func.name)

        # Register module-level statics (design 41). Accessible module-locally;
        # a `public` static is additionally visible to importers.
        for static in getattr(module_ast, 'statics', []):
            with self._declaring(static):
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

        # Check for main function (only when the output needs an entry point)
        if require_main is None:
            require_main = is_entry
        if require_main and not self.namespace.has_function("main"):
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
            if getattr(func, 'is_mono_instance', False):
                # A synthesized instantiation spliced in by the effect pass
                # (design 70). It was already checked where it was built, with
                # errors suppressed on purpose: this clone exists to harvest
                # effect edges, and a genuine instantiation error surfaces
                # through codegen's own monomorphization.
                #
                # Re-checking it HERE would report those suppressed errors as
                # the author's, and they are not the author's — every type in a
                # clone arrived by substitution, so design 132's "a Void you can
                # SEE" rule reads `let result = body(n)` at `R = Void` as a
                # binding of nothing. Only the place lowering's re-entry gets
                # this far (a first pass builds the clone after this loop), and
                # it must reach the same verdict the first pass did.
                kept_errors = len(self.reporter.errors)
                kept_warnings = len(self.reporter.warnings)
                self._check_function(func)
                del self.reporter.errors[kept_errors:]
                del self.reporter.warnings[kept_warnings:]
                continue
            self._check_function(func)

        # Type check method bodies
        for extension in module_ast.extensions:
            self._check_extension(extension)

        # design 70 (A5): build + re-check every queued generic instantiation so
        # its effect node (keyed by the mangled symbol) is populated before the
        # whole-program fixpoint. Splices concrete clones into `module_ast`, which
        # the coroutine transform and codegen then treat as ordinary functions.
        # design 210 unit 4: record this module's checked scope against every
        # source FILE it owns. A GENERIC instantiation is re-checked per
        # instantiation (designs 70/74 — types AND effects both depend on the
        # type arguments), and that recheck belongs in the TEMPLATE's home
        # scope: `boost` is a name in `embedmod` and nowhere else. The key is
        # the file because that is what a declaration carries;
        # `_vis_module_for_source` cannot answer it after the fact (it reports
        # `current_module_path` for anything outside std, which is whoever is
        # being checked NOW rather than who owns the file).
        for _src in _module_source_files(module_ast):
            self._module_scope_by_file[_src] = (module_path, ns)
        self._direct_imports_by_module[module_path] = set(self.current_direct_imports)

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
            with self._declaring(sa):
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

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
from .tierreq import TierRequirementsMixin
from .sigvis import SignatureVisibilityMixin
from .consumes import ConsumesMixin


# design 218 unit 1.5 stage 2 — A MONOMORPHIZED INSTANCE'S DIAGNOSTICS ARE REAL.
#
# The four `del self.reporter.errors[...]` sites in effects.py are gone, §3's
# attribution note is attached, and §1c's provenance skips are named per rule.
# This constant is what the landing flipped, and it is kept as a NAMED SWITCH
# rather than deleted because it is the one line that says which half of the
# 218 charter's diagnosis is closed: "no judgment with real errors ever runs on
# any instance" is no longer true of this compiler.
#
# It was held for one commit on DF-284c — a trait REQUIREMENT had no callable
# method on a PRIMITIVE receiver, so `rank<T: Comparable>`'s `a.compare(&b)` at
# `T = UInt8` resolved abstractly through the bound and nowhere once the clone
# dropped it. That closed with the minimal unit-3 slice the user ruled forward
# (`_primitive_requirement_call`), which routes the concrete receiver to the
# same `comparison_dispatch` design 239 already built for the bound.
INSTANCE_ERRORS_ARE_REAL = True


_BINDING_ID_COUNTER = itertools.count(1)


# design 218c Amendment B1 — A NAMESPACE HOLDS FACTS AND IT HOLDS A VIEW.
#
# The FACT tables (`structs`, `enums`, `functions`, `conformances`,
# `generic_*`, `statics`, …) say what the PROGRAM contains; merging them across
# modules produces exactly the answer codegen works from, and it is the answer
# an instance check needs about a type ARGUMENT, which by construction was
# declared somewhere else.
#
# These are the other kind: one module's VIEW of those facts — which bare name
# means which identity HERE, which names two imports made ambiguous HERE, which
# std names this file opted into, which qualifiers it bound. A merged view is a
# view no module has, and reading one inside a template's body invents both
# ambiguities and absences. So `_instance_check_scope` installs the merged
# namespace and puts these back from the template's HOME module for the
# duration of one instance check.
#
# Adding a field to `Namespace` that is a per-module view means adding it to
# BOTH functions below; a field that is a fact about the program does not
# belong in either. Written out attribute by attribute rather than driven off a
# name list, because a computed `setattr` is exactly what the design-126 AST
# contract (the `astgraft` lane) refuses to let a pass do to an object.


def _swap_view_tables(program_ns, home_ns):
    """Install `home_ns`'s view tables on `program_ns`; return what to restore.

    THE VIEW TABLES, each with what it decides HERE:
      `type_names` / `type_provenance` — which identity a written name denotes
        (design 144); `ambiguous_types` — which names two imports collided on
        (design 26); `directly_accessible` / `allow_all_access` — the bare-name
        opt-in of this file (design 82); `modules` / `nonbinding_qualifiers` /
        `glob_sources` / `selective_sources` / `import_private_names` /
        `import_private_modules` — the qualifiers and import forms this file
        bound (design 150); `module_path` — who is asking.

    A no-op returning None when there is no home module (a single-file compile,
    a synthesized clone with no source), where the program's own view is the
    only one there is.
    """
    if home_ns is None or home_ns is program_ns:
        return None
    saved = (
        program_ns.type_names, program_ns.type_provenance,
        program_ns.ambiguous_types, program_ns.directly_accessible,
        program_ns.allow_all_access, program_ns.modules,
        program_ns.nonbinding_qualifiers, program_ns.glob_sources,
        program_ns.selective_sources, program_ns.import_private_names,
        program_ns.import_private_modules, program_ns.module_path,
    )
    program_ns.type_names = home_ns.type_names
    program_ns.type_provenance = home_ns.type_provenance
    program_ns.ambiguous_types = home_ns.ambiguous_types
    program_ns.directly_accessible = home_ns.directly_accessible
    program_ns.allow_all_access = home_ns.allow_all_access
    program_ns.modules = home_ns.modules
    program_ns.nonbinding_qualifiers = home_ns.nonbinding_qualifiers
    program_ns.glob_sources = home_ns.glob_sources
    program_ns.selective_sources = home_ns.selective_sources
    program_ns.import_private_names = home_ns.import_private_names
    program_ns.import_private_modules = home_ns.import_private_modules
    program_ns.module_path = home_ns.module_path
    return saved


def _restore_view_tables(program_ns, saved):
    """Put `program_ns`'s own view back — `_swap_view_tables`' exact inverse."""
    (program_ns.type_names, program_ns.type_provenance,
     program_ns.ambiguous_types, program_ns.directly_accessible,
     program_ns.allow_all_access, program_ns.modules,
     program_ns.nonbinding_qualifiers, program_ns.glob_sources,
     program_ns.selective_sources, program_ns.import_private_names,
     program_ns.import_private_modules, program_ns.module_path) = saved


def _module_source_files(module_ast):
    """Every distinct source file the declarations of `module_ast` came from.

    A module is a DIRECTORY (design 82 makes each std file its own module, and a
    user module can span several `.saw` files), so "which module owns this
    declaration" is answered per file rather than per AST. Design 210 unit 4
    keys a module's checked scope on this so a generic template can be re-checked
    where it was written.

    ONLY AUTHORED DECLARATIONS ESTABLISH OWNERSHIP (DF-289a). A monomorphized
    clone and a transform-synthesized frame both keep the ORIGINAL's source
    spans — that is what makes their diagnostics anchor at the author's own line
    — so `amplify<Lo>`'s clone and `__Frame_Cell$m$embedmod_charge$1$Lo`, both
    living in the ENTRY ast after the coroutine transform, carry
    `embedmod/lib.saw`. Counting them made the ENTRY module claim that file, and
    the entry is checked LAST, so its claim overwrote the real owner's: on the
    transform's re-entry `_module_scope_for_file('embedmod/lib.saw')` answered
    with the entry's namespace, where `boost` is not a name. That is census
    class 14 (`undefined function boost`, conformance row K22's own shape) —
    DF-206e's costume, worn one pipeline stage later. The file a synthesized
    declaration came from belongs to whoever DECLARED it, so the walk skips
    every declaration that no author wrote, and the caller records with
    `setdefault` so that a claim this test cannot see (an Extension carries no
    provenance flag of its own) still loses to the owner's, which comes first
    in dependency order.
    """
    seen = []
    for group in ('functions', 'structs', 'enums', 'extensions', 'traits',
                  'statics', 'type_aliases'):
        for decl in getattr(module_ast, group, None) or ():
            if (getattr(decl, 'is_mono_instance', False)
                    or getattr(decl, 'is_synthesized', False)):
                continue
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
    # design 188's FRESH-JOURNEY amendment (218c Amendment B4): this binding is
    # a BY-VALUE PARAMETER of the enclosing function or method, so — unlike a
    # local — the value in it was constructed by the caller and handed over,
    # never bound anywhere the program could still name. Read by
    # `_no_move_is_fresh_journey`; see there for why that is the whole
    # difference.
    is_parameter: bool = False
    # DF-288a: this binding NAMES storage somebody else still owns — it is an
    # alias, not an owner, so `move`ing it would hand out a value the referent
    # keeps and both halves would be released. The binding's TYPE cannot say
    # this: a variant-pattern binding out of a `&var Slot` scrutinee is typed
    # `Owned`, exactly as one out of an owned scrutinee is, and only the
    # SCRUTINEE knew the difference. Set at the registration site that knows
    # (`_match_payload_borrows` is the one oracle); read by `_check_move_expr`,
    # beside the `TypeKind.REFERENCE` refusal it extends to the bindings a
    # reference reaches THROUGH.
    borrows_referent: bool = False


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
    handle_id: Optional[int] = None    # the binding the `Task` handle landed in
    handle_name: Optional[str] = None
    # Lines this borrow has already been reported against, so one statement
    # that both reads and writes a root yields one diagnostic rather than a
    # pile (the receiver of `buf.push(9)` is checked twice on the way down).
    reported: set = field(default_factory=set)


@dataclass
class SpawnObligation:
    """One must-consume handle minted by a SINGLETON spawn form (design 242
    ruling 5).

    `Thread.spawn { … }` and `Task.spawn { … }` hand back a handle whose fate is
    load-bearing: dropping it used to JOIN (the thread engine) or silently
    abandon a result (the cooperative one), so the natural fire-and-forget
    spelling did something nobody wrote. Ruling 5 makes every fate explicit —
    the handle reaches `join()`, `detach()` or (cooperatively) `cancel()` on
    every path, or the program does not compile.

    `group.spawn` mints NOTHING here: ruling 6 attaches the obligation to the
    FORM, not to the type, because a group is a declared in-scope consumer whose
    `Deinit` is the join barrier. That is why this record is created in the two
    spawn-form checkers and nowhere else.

    Function-local by construction (ruling 5's v1 fence): the record lives from
    the form to the end of the scope its binding dies in, and a handle that
    leaves the function unconsumed is refused rather than tracked onward.
    """
    type_name: str                     # "Thread" | "VoidThread" | "Task" | "VoidTask"
    form: str                          # "Thread.spawn" | "Task.spawn"
    line: int
    column: int
    binding_id: Optional[int] = None   # the local that took the handle
    binding_name: Optional[str] = None
    consumed: bool = False             # a join/detach/cancel, or 9a storage
    reported: bool = False             # one diagnostic per obligation


@dataclass
class ClosureReturnTarget:
    """The callable a `return` inside a closure literal returns to (design 213).

    A closure literal is a CALLABLE, so everything the checker knows as "the
    function I am currently in" changes at its brace — its return type, and
    whether a raised error has a `catch` on its path. The checker used to keep
    exactly one such answer (`current_function`/`current_method`) and a closure
    body was checked without pushing a new one, so five separate rules read the
    ENCLOSING NAMED function's state through the closure boundary (DF-212a and
    its four siblings; two of them reached codegen and ICEd).

    One record per closure body being checked, innermost last; `_return_target`
    is the single funnel that reads them.

    `expected` is the closure's return type when the call site supplied one (a
    function-typed parameter, an annotated binding). When it is None the return
    type is being INFERRED from the body, so the returns are checked against
    each other instead: the first `return <value>` fills `observed` and later
    ones must agree with it.
    """
    expected: Optional['SawType'] = None
    observed: Optional['SawType'] = None       # first `return <v>` when inferring
    observed_line: int = 0
    observed_column: int = 0
    has_return: bool = False                   # the body contains any `return`
    saw_bare_return: bool = False              # a valueless `return` was seen
    # `try`s raised while the return type was still unknown, replayed against
    # the inferred type once the body has been checked.
    pending_try: list = field(default_factory=list)


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


class TypeChecker(ExpressionsMixin, StatementsMixin, RegistrationMixin, TypeUtilsMixin, EffectsMixin, PlacesMixin, SerdeMixin, TierRequirementsMixin, SignatureVisibilityMixin, ConsumesMixin):
    """Type checks a Saw program."""

    def __init__(self, reporter: ErrorReporter, freestanding: bool = False,
                 runtime_build: bool = False, post_transform: bool = False,
                 no_hidden_alloc: bool = False,
                 target_triple: Optional[str] = None,
                 target_features: Optional[str] = None,
                 runtime_provider: bool = False,
                 mapped_packages: Optional[Set[str]] = None,
                 package_identities: Optional[
                     Dict[Tuple[str, ...], str]] = None):
        self.reporter = reporter
        # design 218 unit 1.5: the MONOMORPHIZED INSTANCE being checked, as
        # `(display, demand-site)`, or None outside one. Set only by
        # `_checking_instance`; read by `_error` for §3's attribution note and
        # by each §1c provenance skip at its own rule.
        self._mono_instance: Optional[Tuple[str, Optional[str]]] = None
        # Whether THIS instance's diagnostics are muted because the abstract
        # layer already reported one — see `_checking_instance`.
        self._instance_muted: bool = False
        # §1c skip 4's input: the by-value parameters of the instance under
        # check whose declared type ARRIVED BY SUBSTITUTION. Empty outside an
        # instance. See `_transfer_is_substituted_param`.
        self._mono_substituted_params: frozenset = frozenset()
        # §1c skip 5's input: whether the RETURN TYPE of the instance under
        # check arrived by substitution. False outside an instance. See
        # `_mono_return_is_substituted`.
        self._mono_substituted_return: bool = False
        # design 188's FRESH-JOURNEY amendment (218c Amendment B4), the two
        # facts its rule is decided from. `_referenced_bindings` holds the
        # `binding_id` of every binding a `&`/`&var` has named, filled at
        # `_check_reference_expr` and never cleared (a `binding_id` is unique
        # for the whole compile, so there is nothing to clear it BETWEEN);
        # `_placement_move_target` is True only while the RHS of a
        # `ptr[i] = ...` through a MUTABLE pointer is being checked. See
        # `_no_move_is_fresh_journey`.
        self._referenced_bindings: set = set()
        self._placement_move_target: bool = False
        # DF-232f: the top-level names bound by `--module-path name=dir`. Each
        # one IS a package (ruled Aug 17): every file under the mapped
        # directory is a sibling, and the entry file — which never appears
        # here — is outside. `_visibility_relation_allows` roots
        # `public(package)` at `(name,)` for these, exactly as it roots std at
        # `("<std>",)`. Without it these modules had NO root, and the tier
        # fell through check_visibility's fail-open arm to plain `public`.
        self.mapped_packages: Set[str] = set(mapped_packages or ())
        # ---------------------------------------------------------------- #
        # DF-232o: THE POISON SET — type names this module was REFUSED.
        #
        # A refusal answers None, and a type name that resolves to nothing is
        # not dropped: it becomes an opaque type of that same name (design 144
        # canonicalization is total, because a bare name may be a type
        # parameter or a forward reference). So the ONE true refusal is
        # followed by a structural mismatch at every use — and the printer
        # renders both sides short, which is how "field `status` expects type
        # `SosStatus` but got `SosStatus`" happens, 100+ times, burying the
        # line that says what is actually wrong.
        #
        # Once a name is refused HERE, every later disagreement about it is
        # that refusal's shadow. `_types_compatible` — the one place two types
        # are judged — answers compatible for a poisoned name, so the cascade
        # never starts. The compile still fails: the refusal was reported.
        #
        # Populated at the two places a TYPE reference is refused by tier: the
        # selective import (`check_module`), and the qualified spelling
        # (`_resolve_qualified_symbol` -> `_note_type_refusal`, which also
        # keeps the refusal itself so `_check_qualified_type_resolves` can say
        # "is public(package) in `m`" instead of "does not resolve").
        # ---------------------------------------------------------------- #
        self._poisoned_type_names: Set[str] = set()
        self._type_refusals: Dict[str, object] = {}
        # DF-247b: the same idea, keyed on the WHOLE dotted spelling. A
        # `data.Data` whose qualifier is not bound here is refused and then
        # keeps its spelling as a name-only type, so every later comparison
        # reports the mismatch that refusal caused ("cannot assign `Data` to
        # variable of type `data.Data`" — the shape DF-247b was filed as). The
        # full spelling is the key, not the simple name the poison set uses,
        # because the BARE `Data` beside it is a perfectly good type and its own
        # mismatches must still be reported.
        self._unbound_qualifier_types: Set[str] = set()
        # The FILES that refusal fired in. A local of the unresolved type makes
        # every read off it answer nothing, so the enclosing body types as no
        # value — DF-232o's "body has no value" shadow, reached through a local
        # rather than through the signature. Scoped to the file because the
        # refusal is reported there and that file already fails to compile.
        self._unbound_qualifier_files: Set[str] = set()
        # DF-232n: module path -> package identity, for every module the driver
        # loaded (`ModuleResolver.package_identity`). A package reached by
        # RELATIVE path has no mapped name to root it at, so this is what makes
        # `public(package)` real for it; without it the tier fell through to
        # plain `public` for every such consumer.
        self.package_identities: Dict[Tuple[str, ...], str] = dict(
            package_identities or {})
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
        # ---------------------------------------------------------------- #
        # THE POST-TRANSFORM EXEMPTIONS, ONE FLAG PER GATE (design 218a §6).
        #
        # `post_transform` used to BE the exemption: one bool relaxing six
        # unrelated gates, each justified on its own terms and none of them
        # named, so nothing stopped a seventh gate from being swept in
        # unaudited. Splitting it does not change behaviour by one bit — every
        # flag is `post_transform` today — but it makes each relaxation a thing
        # with a name, a docstring at its read site, and a disposition:
        #
        #   E1 exempt_hidden_alloc          PERMANENT (provenance, not safety)
        #   E3 exempt_ext_scope             PERMANENT (source-level rule)
        #   E4 exempt_shadowed_qualifier    PERMANENT (warnings describe source)
        #   E5 exempt_prelude_gate          PERMANENT (source-level rule)
        #
        # E6 (design 132's lost-write rule) went at stage 3, which is what the
        # split was for: the closures the transform emits are ordinary checked
        # code now, so they pass the real check.
        #
        # E2 (design 130's unsafe trigger rule) is GONE as of design 222 unit 4,
        # and the three units before it are why. Stage 3 could only NARROW it:
        # the declarations the transform AUTHORS declare `unsafe` honestly
        # (`unsafe_decl_checked` — see `_unsafe_check_exempt`), but it also
        # spliced pointer CASTS into bodies somebody else wrote — a spawn site's
        # `(&group) as UnsafeConstPointer<TaskGroup>`, a drive site's receiver
        # cast, a reference argument's — 166 corpus files' worth, measured. Unit
        # 2 moved all three crossings out of the rewritten body and into the
        # generated declaration that already says `unsafe` about them: the call
        # sites write `&group` and `&c`, ordinary references an author could have
        # written. So there is nothing left to excuse. The design-130 rule now
        # runs on EVERY declaration in the post-transform AST, authored and
        # rewritten alike, with no exemption at all.
        #
        # What the transform genuinely cannot express safely is a NAMED list with
        # written arguments, in the design 218 brief's ratified section — not a
        # flag. Its one addition from this work is the design-91 wake latch
        # (design 222 unit 3), whose wrapper was built, run, and refused for
        # laundering the obligation out of every signature.
        #
        # (E7 is the parameter threading through `sawc.py`; it follows this
        # split mechanically, since every flag is derived here.)
        #
        # NONE of them is an OWNERSHIP exemption. Those ride per-node marks the
        # transform stamps (`frame_place_read`, `frame_move_read`,
        # `frame_owning_read`), and they are what the migration to `Slot<T>`
        # actually deletes — a distinction the single bool made easy to lose.
        # ---------------------------------------------------------------- #
        self.exempt_hidden_alloc = post_transform
        self.exempt_ext_scope = post_transform
        self.exempt_shadowed_qualifier = post_transform
        self.exempt_prelude_gate = post_transform
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
        # design 260: every `consumes` body checked in this compile, as
        # `(method, struct_name)`. Its two SUSPENDING-body fences depend on the
        # whole-program effect fixpoint, so they are decided in
        # `finalize_effects` rather than at the declaration.
        self._consumes_bodies: List[Tuple['Method', Optional[str], bool]] = []
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
        # design 218 section 4: how deep we are inside closure bodies that
        # captured the receiver as a SHARED borrow (`[&self]`) from a `&var self`
        # method. Read ONLY through `_self_borrow_is_exclusive`.
        self._shared_self_capture_depth = 0
        # design 213: the return target of each enclosing closure body, innermost
        # last. Read ONLY through `_return_target`.
        self._closure_returns: List[ClosureReturnTarget] = []
        # Track break value types for each loop level
        # Each entry is (expected_type: Optional[SawType], is_infinite: bool, has_break: bool)
        self.loop_break_info: List[Tuple[Optional[SawType], bool, bool]] = []
        # Per-function, scope-aware move state for use-after-move detection.
        # Keyed by the binding's `VariableInfo.binding_id`, so that same-named
        # bindings in different functions/scopes never interact and a `let`/`var`
        # shadow gets fresh state.
        # value = (var_info, name, move_line, move_column, provisional)
        # design 219 wave C: `provisional` marks a transfer of an ABSTRACT-tier
        # value, which is a move if nothing uses the binding again and a
        # duplicate if something does. The move dataflow decides — see
        # `typechecker/tierreq.py`.
        self.moved_bindings: Dict[int, Tuple['VariableInfo', str, int, int, bool]] = {}
        # design 219 wave C: the tier-requirement accumulator for the
        # declaration whose body is being checked, the declaration it belongs
        # to, and the call sites owing a discharge (resolved at finalize).
        self._tier_req_acc: Optional[Dict[str, tuple]] = None
        self._tier_req_decl = None
        self._tier_obligations: List[tuple] = []
        # design 189: the reference captures spawned tasks are holding RIGHT
        # HERE. Function-local like the move state above, and conservative at
        # every join point — a borrow released on only one branch comes back at
        # the end of the branch, because the other path never joined.
        self._task_borrows: List['TaskCaptureBorrow'] = []
        # The borrows the spawn in the statement being checked just opened,
        # waiting for the `let h = ...` binding that will carry them. Cleared at
        # every statement boundary, so nothing else can claim them.
        self._pending_task_borrows: List['TaskCaptureBorrow'] = []
        # design 242 ruling 5: the must-consume handles minted by a singleton
        # spawn form and still live in the function being checked, plus the one
        # the statement being checked just minted and nothing has claimed yet.
        # Both are cleared per function, exactly as the borrow state above is.
        self._spawn_obligations: List['SpawnObligation'] = []
        self._pending_spawn_obligation: Optional['SpawnObligation'] = None
        # Spawn-form nodes whose handle is consumed by the method call wrapping
        # them (`Thread.spawn { … }.join()`), so the form mints no obligation.
        self._chained_spawn_consumes: set = set()
        # Structs whose copy() is compiler-derived (memberwise), checked for
        # NoCopy fields after all conformances are registered.
        self._derived_copy_structs: set[str] = set()
        # Enums whose copy() is compiler-derived payload-deep (design 139): a
        # declared `@synthesize extension E: Copy|ExplicitCopy {}`.
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
        # DF-232j: the namespace layer decides `public(package)` for every
        # qualified reach, so it needs the package names too. Stamped here and
        # on every per-module namespace `check_module` builds.
        self.namespace.mapped_packages = frozenset(self.mapped_packages)
        # DF-232n: same stamping, same reason, for the relative-path half of the
        # question. The map is shared by reference, never copied per namespace.
        self.namespace.package_identities = self.package_identities

        # Current module path during multi-module type checking
        self.current_module_path: Tuple[str, ...] = ()

        # DF-243b: the SOURCE FILE of the module being checked, for a diagnostic
        # raised where no function or method is in scope — a `static`, a
        # `static_assert`, a struct field, an import. Without it the reporter
        # falls back to the ENTRY file and prints the dependency's line numbers
        # under the entry's path, so a reader follows the diagnostic to the wrong
        # file at a line it does not have. `None` on the single-file path, where
        # the entry IS the module and the fallback is already right.
        self.current_module_source: Optional[str] = None

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
        # Design 249: free-function name -> the MODULES of this compilation that
        # declare one. Taken by the driver over the parsed module set before any
        # module is checked, so `_free_function_symbol_base` can decide a
        # declaration's codegen base without depending on module order — a name
        # more than one module owns is `$M$`-tagged per module, and a name only
        # one module owns keeps the plain spelling it has always had.
        self.free_function_owners: Dict[str, Set[Tuple[str, ...]]] = {}
        # design 45: the suspending METHODS the effect fixpoint settled on,
        # handed back by the coroutine transform for its own second pass.
        self._suspending_methods_set: Optional[set] = None
        # design 223: the same census under design 206's SHARPER question —
        # which methods REALLY suspend, as against the conservative set above,
        # which also holds the ones that "suspend" only because they call
        # through a non-`sync` function value (`Vector.map`). The transform
        # decides whether an un-nameable call site is REFUSED from this one; the
        # difference between the two sets is exactly the calls that must not be.
        self._really_suspending_methods_set: Optional[set] = None

        # design 204: the source file of the declaration currently being
        # REGISTERED, for `_type_lookup_module`. Registration resolves a
        # signature before any body is entered, so the current-function path
        # cannot answer there; `_declaring` maintains this.
        self._decl_source_file: Optional[str] = None

        # design 210 unit 4: source FILE -> the (module path, namespace) that
        # file's declarations were checked under, filled by `check_module` as
        # each module finishes. Read by `_instance_check_scope`, which is how a
        # GENERIC instantiation gets re-checked where its template was written
        # instead of where the call that reached it was.
        self._module_scope_by_file: Dict[str, Tuple[Tuple[str, ...], Any]] = {}
        # Amendment A1 (DF-285b): the same map for STD's files, recorded by the
        # builtin typechecker's own `check` and handed over with its cached
        # namespace. Read through `_module_scope_for_file`, never directly.
        self._std_module_scope_by_file: Dict[str, Tuple[Tuple[str, ...], Any]] = {}
        # …and the design-142 direct imports each module was checked with, which
        # `Namespace` does not carry. Same lifetime, same reader.
        self._direct_imports_by_module: Dict[Tuple[str, ...], Set[Tuple[str, ...]]] = {}
        # design 254: module -> the modules it `public import`s, any form. Design
        # 229 records a re-export only NEGATIVELY (an ordinary import is noted, a
        # public one simply is not), and extension scope needs the POSITIVE edge:
        # `_close_over_public_imports` walks this graph to widen the direct-import
        # set above. Filled by `check_module` as each module finishes its import
        # list, and read by the modules that import it — which is well-ordered,
        # since modules are checked in dependency order (a cycle is DF-232e's
        # error, reported before any of this).
        self._public_imports_by_module: Dict[Tuple[str, ...], Set[Tuple[str, ...]]] = {}

        # design 194 unit 4: the prelude-gate reports already made, keyed by
        # (module, name, line, column). The front half re-enters the same AST
        # (place lowering, the coroutine transform's re-check), so a rule that
        # fires per resolution would print each diagnostic more than once.
        self._gate_reported: set = set()

        # design 226: the same, for the `FuncPointer<F>` argument rule. Its own
        # set because the two rules answer different questions about the same
        # node and either may fire without the other.
        self._funcpointer_reported: set = set()

        # The signature-visibility rule's own report set ("a public API needs
        # public types", user ruling Aug 21 — see typechecker/sigvis.py). Keyed
        # by (file, line, column, type name, position): one `SawType` object is
        # shared by a symbol table and the AST, and the front half re-enters the
        # same AST, so the same refusal is reachable more than once.
        self._sigvis_reported: set = set()

        # design 241 unit 1 (DF-225b): every name this compilation unit's AST
        # declares as a TYPE — struct, enum, trait, alias, plus the
        # associated-type names a trait declares and an extension assigns.
        # Stamped by `check`/`check_module` BEFORE any of them is registered,
        # because the undefined-type rule fires from the design-194 funnel and
        # three of that funnel's entries run DURING registration, where a
        # forward reference (a field naming an enum, which registers a pass
        # later) is not in the namespace yet. Saw has no forward declarations,
        # so a name the unit declares anywhere is defined everywhere in it.
        self._unit_type_names: set = set()

        # Register built-in functions
        self._register_builtins()

    # ------------------------------------------------------------------
    # design 213: THE ONE ANSWER TO "WHAT CALLABLE AM I RETURNING TO?"
    # ------------------------------------------------------------------
    def _return_target(self) -> Optional[ClosureReturnTarget]:
        """The innermost enclosing CLOSURE's return target, or None in a
        function/method body.

        THE FUNNEL for design 213. A closure literal is a callable: a `return`
        written inside one returns from the CLOSURE, and an error it raises
        propagates out of the CLOSURE. Every rule that asks "what does control
        leaving here go to?" must ask here first, and only fall back to
        `current_function`/`current_method` when this returns None.

        ENTRY POINTS (the position matrix DF-212a's sweep produced — each was
        an independent copy of the same mistake before this funnel existed):
          1. `_check_return_statement`      (statements.py) — the return's type
          2. `_check_if_expr`               (expressions.py) — value-`if` arms'
                                             Result auto-wrap reconciliation
          3. `_check_match_expr`            (expressions.py) — match arms', ditto
          4. `_validate_error_propagation`  (expressions.py) — `try`'s target
          5. `_check_closure`               (expressions.py) — pushes/pops the
                                             record, and clears the enclosing
                                             `try {} catch {}` state, which is
                                             the same leak in boolean form

        Pushed by `_check_closure` around the body check and nowhere else.
        """
        return self._closure_returns[-1] if self._closure_returns else None

    def _enclosing_return_type(self) -> Optional['SawType']:
        """The return type of the innermost enclosing callable, resolved.

        None means "no answer available" — either there is no enclosing callable
        at all, or we are in a closure whose return type is still being inferred.
        Callers that must distinguish the two ask `_return_target()` directly.
        """
        target = self._return_target()
        if target is not None:
            return (self._resolve_type(target.expected)
                    if target.expected is not None else None)
        if self.current_method is not None:
            return self._resolve_type(self.current_method.return_type)
        if self.current_function is not None:
            return self._resolve_type(self.current_function.return_type)
        return None

    def _get_current_source_file(self) -> Optional[str]:
        """Get the source file from the current method or function context."""
        if self.current_method and hasattr(self.current_method, 'source_file'):
            return self.current_method.source_file or None
        if self.current_function and hasattr(self.current_function, 'source_file'):
            return self.current_function.source_file or None
        return None

    def _diagnostic_source_file(self) -> Optional[str]:
        """The file a diagnostic raised right now belongs to (DF-243b).

        The current method or function when there is one, and otherwise the
        MODULE being checked. That second fallback is what makes a module-level
        refusal — a `static`, a `static_assert`, a struct field, an import —
        name the file it is in. Without it the reporter fell back to the ENTRY
        file and printed the DEPENDENCY's line numbers under the entry's path,
        so a reader following the diagnostic opened the wrong file at a line it
        does not have; a missing file is at least visibly missing, where a wrong
        one looks authoritative.

        Deliberately NOT `_get_current_source_file` itself: that one also
        answers the member-VISIBILITY gate (`_accessor_vis_module`), where the
        module path is already the right answer at module level and a std file's
        source would re-key the accessor. Reporting and access control ask the
        same-sounding question for different reasons.
        """
        return self._get_current_source_file() or self.current_module_source

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
        from type_identity import std_leaf
        if not source_file:
            return self.current_module_path
        leaf = std_leaf(source_file)
        if leaf is not None:
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
        name in its signature resolves against ITS module's private types.

        Also the declaration ANCHOR (design 255 / SL-4): a name written in a
        SIGNATURE is resolved before any body is entered, so design 192's
        expression/statement breadcrumb is empty there and a use-site
        diagnostic raised from the lookup has nothing else to point at."""
        saved = self._decl_source_file
        saved_node = getattr(self, '_declaring_node', None)
        self._decl_source_file = getattr(decl, 'source_file', None) or saved
        self._declaring_node = decl
        try:
            yield
        finally:
            self._decl_source_file = saved
            self._declaring_node = saved_node

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

    # ------------------------------------------------------------------ #
    # THE TEMPLATE STORE — the capture funnel (design 218c T1 / Amendment A1,
    # obligation 1).
    #
    # A generic template is snapshotted PRISTINE — before any body check has
    # mutated an annotation — because that is the artifact §4's
    # "invalidation: none" argument is written about: nothing edits a template
    # after capture, so an instance cloned from one is reproducible and every
    # cache hit stays valid.
    #
    # ENTRY POINTS — every path that checks a whole unit's bodies:
    #   * `check_module` — the entry file and every user module it imports,
    #     called once per module by the entry typechecker.
    #   * `check` — the whole-program path, which is what STD goes through.
    #     std's bodies are checked exactly once, by the separate typechecker
    #     inside `build_builtin_namespace`, and its result is cached; before
    #     Amendment A1 that typechecker took no snapshot at all, so the store
    #     an entry compile inherited was EMPTY for the library that supplies
    #     almost every instance (DF-285b: 0/0/0 against 111 demanded
    #     instances on `hello.saw`).
    # ------------------------------------------------------------------ #
    def _capture_pristine_templates(self, module_ast) -> None:
        """Snapshot every generic template in `module_ast`, pre-body-check.

        THE ONE CAPTURE POINT, and its two ENTRY POINTS (obligation 1 — the
        block above says why each exists):
          * `check_module` — the entry file and every user module it imports.
          * `check` — the whole-program path, which is what STD goes through.
        A third caller would be a third store, so add one here rather than
        beside it.
        """
        # design 70 (A5): pristine (pre-body-check) copies of every generic
        # function template, so a suspending instantiation can be cloned +
        # substituted + re-checked for per-instantiation effect inference.
        import copy as _copy
        for func in module_ast.functions:
            if getattr(func, 'type_params', None) and not getattr(
                    func, 'is_mono_instance', False):
                # Design 105: a generic OVERLOAD carries a distinct `$OL$` base
                # symbol; key its pristine template by that so two overloads of
                # one name don't collide (a lone generic keeps its plain-name
                # key).
                key = getattr(func, 'mangled_symbol', None) or func.name
                self._pristine_generics[key] = _copy.deepcopy(func)
        # Method-level generic methods on a NON-generic extension: pristine
        # snapshot keyed by (struct, method), with the owning extension
        # (design 70).
        for ext in module_ast.extensions:
            if getattr(ext, 'type_params', None):
                # design 74 (A5-rest, shape 2): an extension on a GENERIC struct
                # (`extension Holder<T>`). Snapshot every method (not just
                # method-level generics): driving `__saw_drive(b.run())` for a
                # concrete receiver `Holder<Int>` monomorphizes the method over
                # the STRUCT's type params so the coroutine frame's `__recv`
                # gets a concrete layout. Keyed by (struct, method); the ext
                # carries the struct's type params for substitution.
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

    # ---------------------------------------------------------------- #
    # THE UNION STORE (Amendment A1). The entry typechecker's own
    # `_pristine_*` dicts hold the templates IT checked; the `_std_pristine_*`
    # dicts hold the ones the builtin typechecker checked, handed over with the
    # cached `(builtin_ast, builtin_ns)` pair. Two dicts and not one because
    # the two capture points belong to two different compiles: a std template
    # is snapshotted once per CACHE BUILD, an entry template once per compile,
    # and merging them would make the existing design-70/74 builders — which
    # decline a template with no pristine copy, and have never covered a std
    # generic (`_build_fn_mono`'s "design 68 territory" comment) — silently
    # start serving std. Widening THAT is stage 3c's cutover, not the store's.
    # Reads go through these three lookups, entry first.
    # ---------------------------------------------------------------- #
    def pristine_generic(self, key):
        """The pristine template for a generic free function, or None."""
        found = self._pristine_generics.get(key)
        if found is None:
            found = self._std_pristine_generics.get(key)
        return found

    def pristine_generic_method(self, struct_name, method_name):
        """(Method, Extension) for a method-level generic on a non-generic
        extension, or None."""
        found = self._pristine_generic_methods.get((struct_name, method_name))
        if found is None:
            found = self._std_pristine_generic_methods.get(
                (struct_name, method_name))
        return found

    def pristine_generic_struct_method(self, struct_name, method_name):
        """(Method, Extension) for a method on a GENERIC struct's extension, or
        None."""
        found = self._pristine_generic_struct_methods.get(
            (struct_name, method_name))
        if found is None:
            found = self._std_pristine_generic_struct_methods.get(
                (struct_name, method_name))
        return found

    def _module_scope_for_file(self, source_file):
        """The (module path, namespace) a declaration's FILE was checked in.

        The union of the entry compile's own record and std's, for the reason
        the template store is a union — see above. Returns None for a file
        neither compile placed (a single-file compile, a synthesized clone with
        no source)."""
        if not source_file:
            return None
        entry = self._module_scope_by_file.get(source_file)
        if entry is None:
            entry = self._std_module_scope_by_file.get(source_file)
        return entry

    @contextmanager
    def _instance_check_scope(self, decl, type_map=None, program_namespace=None):
        """THE ONE SCOPE a monomorphized instance is checked in.

        Design 210 unit 4 gave this its first shape and Amendment B1 gave it its
        second; both halves are still here, and the split between them IS the
        rule.

        TWO INPUTS.

        1. `program_namespace` — the MONOMORPHIZER'S MERGED namespace, the same
           artifact codegen sees. It answers every PROGRAM-WIDE question the
           check asks about a TYPE ARGUMENT: what its name denotes, what it
           conforms to, which copy tier it is on, which extensions exist for it.
           Those are facts about the program, not about a module, and asking
           them inside one module's namespace asks the wrong namespace — which
           is what the Sep-1 census found (`designs/reviews/splice-census-sep1.md`
           §3 M1): inside `std/vector`'s scope a corpus `Handle` is an
           `is_abstract_type_name`, so `copy_tier` answers `abstract`, every
           conformance answers False and the check refuses code that compiles
           and runs. Four whole classes and roughly a fifth of the census volume
           were that, and `_lend_instantiation_types` — the attempt to carry the
           arguments across by hand — copies nothing for a type declared outside
           the lender's own `structs`/`enums` tables.

        2. The template's HOME MODULE (`decl.source_file`) — VISIBILITY, and
           nothing else. `current_module_path` is what design 80/82's member and
           name gates read; `current_direct_imports` is what design 142's
           extension lookup reads; `_declaring` anchors design 204's type-name
           lookup at the template's own file. That is what "the home module
           scope" was ever for: a template in `embedmod` calling `embedmod`'s
           private `boost` is judged where its author wrote it (DF-206e), and a
           private sibling stays reachable because the merged namespace holds
           it under the same name and the module path says the caller is
           allowed to see it.

           The home module's contribution also includes the namespace's own
           VIEW tables — see `_swap_view_tables`. A namespace holds two kinds of
           thing and the distinction is the whole of B1: `structs`, `enums`,
           `functions`, `conformances`, `generic_*` are facts about the
           PROGRAM, and `type_names` / `ambiguous_types` / `directly_accessible`
           / the qualifier bindings are one module's VIEW of them — which bare
           name means which identity HERE, which names are ambiguous HERE,
           which std intrinsic this file imported. Merging the second kind
           produces a view no module has: on
           `examples/d144_private_type_identity.saw` the merged
           `ambiguous_types` says `Header` is ambiguous between two modules
           that std/vector never heard of, and the merged
           `directly_accessible` has lost the `import std.task` an embedded
           module wrote. So the view tables travel with the home module and the
           fact tables with the program, which is what the two inputs mean.

        ENTRY POINTS (obligation 1):
          * `monomorphize.measure_splice_all`'s two materializers — the phase-2
            instance check, which supplies the merged namespace.
          * `_build_fn_mono`, `_splice_fn_mono`, `_build_method_mono`,
            `_build_generic_struct_method_mono` — the four design-70/74 builders
            in `effects.py`.

        THE `program_namespace=None` ARM, argued rather than left implicit: the
        four design-70/74 builders run inside `check_entry`, and the per-module
        namespaces are not merged until `check_entry` has returned — so at that
        point in the pipeline there is no program namespace to pass. That arm
        keeps design 210's original behaviour exactly (install the home
        namespace, lend the instantiation's type arguments into it), which is
        what those four have always done. It is not a second policy: it is the
        same policy with the best namespace available, and the population it
        covers is the driven/spawn set the effect pass builds early.

        A declaration whose file was never recorded — a single-file compile, a
        synthesized clone with no source — has no home module, so only the
        program namespace applies. Amendment A1 gave the builtin typechecker the
        same per-file record, so `_module_scope_for_file` answers for a std file
        as it answers for a user module's.
        """
        entry = self._module_scope_for_file(getattr(decl, 'source_file', None))
        if entry is None and program_namespace is None:
            with self._declaring(decl):
                yield
            return
        saved_ns = self.namespace
        saved_path = self.current_module_path
        saved_imports = self.current_direct_imports
        home_path, home_ns = entry if entry is not None else (saved_path, None)
        views = None
        if program_namespace is not None:
            # Program-wide facts from the merged namespace; the home module
            # supplies visibility below and nothing else.
            views = _swap_view_tables(program_namespace, home_ns)
            self.namespace = program_namespace
        else:
            # The instantiation map: the caller's concrete type arguments, lent
            # into the template's scope so `w.seed()` finds the caller's
            # conformance. Only the no-program-namespace arm needs it — the
            # merged namespace already holds every one of them.
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
            if views is not None:
                _restore_view_tables(program_namespace, views)
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
        at its call site rather than again at every rewritten hop.

        E1 (design 218a §6), and PERMANENT: a provenance rule, not a soundness
        gate. Re-counting the same construct after the rewrite would
        double-report it."""
        if not self.no_hidden_alloc:
            return False
        if getattr(self, '_checking_builtins', False):
            return False
        if self.exempt_hidden_alloc or self._in_synthesized_context():
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

    # design 221 Part C (DF-220c). A program's exit status is one small integer,
    # so `main` may say exactly four things: nothing, a status, "this can fail"
    # with no status, or "this can fail" with one.
    _MAIN_RETURN_RULE = ("`main` must return `Void`, `Int`, `Result<Void, E>` "
                         "or `Result<Int, E>`")

    def _check_main_return_type(self, program) -> None:
        """Hold `main` to the four return types the exit status can carry.

        Unchecked until design 221, and the shapes it let through did not fail
        quietly: `main() -> String` compiled clean and exited with the low byte
        of a HEAP POINTER, and `main() -> Result<Int, E>` emitted a
        struct-returning `@main` against a C ABI expecting `int` (status 138 on
        this host, meaningless on any). The typechecker asked only whether
        `main` existed.

        Runs on whatever module declares a top-level `main`, and runs again on
        the transform's re-entry — where `main` is a synthesized entry executor
        whose return type is `Void`, `Int`, or exactly what the user's `main`
        declared, so the rule holds there by construction.

        `E` carries no separate obligation here: what the Err path needs is
        rendering, and the synthesized `__saw_main_exit_code` (built from main's
        own signature, at main's own line) asks for it in the ordinary way — a
        non-`Printable` error type is the ordinary not-`Printable` diagnostic,
        pointing at `main`.
        """
        main = next((f for f in getattr(program, 'functions', [])
                     if f.name == "main"), None)
        if main is None:
            return
        ret = main.return_type
        if ret is None or ret.kind == TypeKind.VOID or ret.kind == TypeKind.INT:
            return
        if ret.is_result():
            ok = ret.unwrap_result_ok()
            if ok is None or ok.kind in (TypeKind.VOID, TypeKind.INT):
                return
        self.reporter.error(
            ErrorKind.TYPE_MISMATCH,
            f"{self._MAIN_RETURN_RULE}, but returns `{ret}`",
            getattr(main, 'line', 1) or 1, getattr(main, 'column', 1) or 1,
            hint="the exit status is an integer: return `Int` for the status, "
                 "`Result<Int, E>` to report a failure as well, `Result<Void, "
                 "E>` when only the failure matters, and nothing at all when "
                 "the program cannot fail",
            source_file=getattr(main, 'source_file', None) or None,
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
        """Whether the design-130 trigger rule looks away from this declaration.

        ONE standing reason, and it is about AUTHORSHIP: the DERIVED bodies
        (copy/equals/compare/hash) traffic in whatever their source type holds
        and have no declaration for an author to mark. The post-transform PASS is
        no longer a reason — E2 is deleted (design 222 unit 4), so a rewritten
        user body is held to the rule exactly as its pre-transform self was. It
        can be, because since unit 2 the transform splices no pointer into it:
        a drive site writes `&c`, a spawn site writes `&group`, and the crossing
        happens inside the generated driver or helper.

        `unsafe_decl_checked` OVERRIDES the derived-body reason, and is design
        218 stage 3's move: a declaration the coroutine transform AUTHORS carries
        the transform's own answer about what it touches, and is judged like any
        hand-written one. A resume body names unsafe types by construction (the
        `__io_tok` latch casts `&self.__wake`, a method frame binds an
        `UnsafeRef`, a spawn root reaches its cell through one), so it SAYS
        `unsafe` and satisfies the rule rather than being excused from it — and a
        wrong answer is a compile error on generated code.

        §1c SKIP 6 (design 218c Amendment B3) is the second standing reason, and
        it MINTS NO POLICY — design 136 already ruled this position. Its rule is
        that unsafety is judged on the type AS WRITTEN: "a generic `(&T) sync ->
        R` slot is judged against `T` and NEVER RE-JUDGED for a
        `T = UnsafePointer<Int8>` instantiation". A monomorphized clone is
        exactly that re-judgment, so the trigger rule looks away from it for the
        same authorship reason the derived bodies get: no author wrote the
        signature it would name. The Sep-1 census's classes 4/6/7 are what that
        costs when it is not applied — 118 raw records over three message
        shapes, whose corpus carrier is not a user's
        `Vector<UnsafePointer<Int8>>` at all but the COROUTINE FRAME's own
        `Slot<T>` (`Slot<UnsafePointer<Bool>>.{empty,of,put,take,clear}`) and
        the place lowering's window result type `__R`. Nobody wrote either; the
        compiler's frame synthesis put the pointer there, which is why design
        219 wave C's per-instance unsafe DERIVATION — a refusal anchored at the
        CALL — never fires for them either. The template's own authored
        signature is judged as it always was."""
        if getattr(node, 'unsafe_decl_checked', False):
            return False
        return (getattr(node, 'is_mono_instance', False)
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

    def _visibility_relation_allows(self, def_module: Tuple[str, ...],
                                    visibility: Visibility,
                                    accessor: Tuple[str, ...],
                                    package_root: Optional[Tuple[str, ...]]
                                    = None) -> bool:
        """Design 80's visibility relation between two NAMED modules — the
        typechecker's door onto `Namespace.visibility_relation_allows`, which
        is the one place `public(package)` / `public(parent)` / `private` is
        decided. The arms (std's root, DF-232f's mapped-package root) live
        THERE, not here: DF-232j found the namespace layer deciding the same
        question with no root at all, because the roots had been computed only
        on this side of the boundary.

        ENTRY POINTS (obligation 1), each naming its own accessor because they
        ask the question at different moments:
          * `_member_gate_allows` — the field/method/type gate. The accessor is
            the module of the code being checked (`_accessor_vis_module`).
          * `check_module`'s SELECTIVE-IMPORT and GLOB arms (DF-229c,
            DF-232k), via `_selection_visible` — the accessor is the IMPORTING
            module, passed explicitly: the import list is processed before
            `self.namespace` becomes this module's, so the ambient answer would
            name the previous module.
          * `Namespace._resolve_parts.is_visible` — THE QUALIFIED REACH
            (DF-232j), which reaches the funnel WITHOUT passing through here:
            every `m.X`, every chain hop, every dotted `resolve()`. Its
            accessor is threaded from the typechecker's member-access, type-
            resolution and trait-lookup sites, each of which passes
            `_accessor_vis_module()`.

        Same-module access is always allowed; everything else follows the
        top-level visibility rules."""
        return self.namespace.visibility_relation_allows(
            def_module, visibility, accessor, package_root)

    def _note_type_refusal(self, written: str, refusal) -> None:
        """Record that a TYPE reference was refused by tier (DF-232o).

        Two things come of it, and both are about the diagnostics downstream:
        `_check_qualified_type_resolves` names the TIER instead of saying the
        name "does not resolve", and `_types_compatible` stops reporting the
        structural mismatch a refused name causes at every later use — the
        refusal is the cause, and one report of a cause beats fifty of its
        shadow.

        Keyed on the SIMPLE name, which is what the fabricated opaque type
        carries; an identity-carrying spelling reduces to the same key.
        """
        name = getattr(refusal, 'name', None)
        if not name:
            return
        self._type_refusals[written] = refusal
        self._poisoned_type_names.add(name)

    def _poison_refused_type_name(self, name: str) -> None:
        """The selective-import half of `_note_type_refusal` (DF-232o), where
        the refusal is reported by `check_module` itself and only the poison is
        owed."""
        if name:
            self._poisoned_type_names.add(name)

    def _report_visibility_refusal(self, refusals, line: int, column: int,
                                   surface_hint: Optional[str] = None) -> bool:
        """Report the design-80 tier refusal a qualified reach hit, if any.

        A `Namespace.resolve` that answered None has to say WHICH None it
        meant: the name is absent, or the name is there and this module is not
        entitled to it. This reports the second — naming the tier and the
        DEFINING module, the two facts a reader needs to act — and answers
        whether it did, so the caller falls through to its "no such symbol"
        diagnostic only when the name really is absent (DF-232j).

        Same wording as `check_module`'s selective-import arm, which is the
        same refusal reached at the other spelling.

        A design-229 SURFACE hint wins outright: "the module merely imports
        this name" is a more specific story than the name's tier, and it comes
        with the two concrete outs (`public import` here, or import the
        dependency directly). The caller's own diagnostic carries it."""
        if not refusals or surface_hint is not None:
            return False
        refusal = refusals[0]
        self._error(
            ErrorKind.UNKNOWN_TYPE,
            f"`{refusal.name}` is {self._vis_word(refusal.visibility)} in "
            f"`{refusal.module_label}`",
            line, column,
            hint=f"mark it `public` in `{refusal.module_label}` to expose it — "
                 f"a `public import` re-export hands on the name and its "
                 f"module's extension scope, never a wider tier")
        return True

    def _member_gate_allows(self, def_module: Tuple[str, ...],
                            visibility: Visibility) -> bool:
        """Whether the code currently being checked may reach a member with the
        given defining module + visibility (design 80)."""
        return self._visibility_relation_allows(
            def_module, visibility, self._accessor_vis_module())

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
    #
    # Design 254 widened the SECOND place, and only that one: the direct-import
    # set is closed over `public import` edges, transitively. A facade that
    # republishes a module republishes its extension neighbourhood with it — the
    # hazard design 142 exists to stop is an UNRELATED transitive dependency
    # changing what a call resolves to, and a `public import` is the facade
    # author's deliberate statement that the module is part of their surface.
    # The widening happens once, in `_close_over_public_imports`, before any body
    # of the module is checked; nothing here knows the difference.
    # ------------------------------------------------------------------ #
    def _close_over_public_imports(self, direct: Set[Tuple[str, ...]]) -> None:
        """Widen `direct` (a file's design-142 direct imports) with every module
        reachable from it along `public import` edges (design 254). In place.

        THE ONE CHOKEPOINT, called from `check_module` once the import list has
        been walked — never per import form, which is how the three forms stay
        one rule: each records its module-level edge and this decides what the
        edges mean.

        Transitive, so a chain of facades forwards the whole way, and cycle-safe
        by the visited set. A malformed graph is DF-232e's error upstream, but
        this may not HANG on one: it runs on the same pass that reports it."""
        frontier = list(direct)
        visited = set(direct)
        while frontier:
            module = frontier.pop()
            for onward in self._public_imports_by_module.get(module, ()):
                if onward in visited:
                    continue
                visited.add(onward)
                direct.add(onward)
                frontier.append(onward)

    def _ext_scope_allows(self, method_info, struct_info) -> bool:
        """Whether an extension method is IN SCOPE for the code being checked
        (design 142). Orthogonal to `_member_gate_allows`, which asks whether its
        visibility permits the access; a method must pass both.

        `current_direct_imports` arrives already closed over `public import`
        (design 254), so the final clause covers both the file's own imports and
        the modules its facades hand on."""
        # The coroutine transform re-checks its own output, splicing bodies from
        # every module into one AST — provenance no longer describes an import
        # graph there. The rule is a source-level one, like the unsafe trigger.
        #
        # E3 (design 218a §6), and PERMANENT: checked correctly on pass 1, and
        # the splice cannot reconstruct an import graph it has already merged.
        if self.exempt_ext_scope or self._in_synthesized_context():
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
        unconditionally.

        E4 (design 218a §6), and PERMANENT: a warning describes what an author
        wrote, and the transform's bindings are not written by anyone."""
        if getattr(self, '_checking_builtins', False):
            return
        if self.exempt_shadowed_qualifier or self._in_synthesized_context():
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

    # ---------------------------------------------------------------- #
    # Design 229's teaching case. A name refused because the module in hand
    # only IMPORTS it is a different mistake from a name that does not exist,
    # and it has two fixes — one at the module, one at the use site. Both are
    # named, along with the dependency the name really lives in.
    # ---------------------------------------------------------------- #
    def _not_reexported_hint(self, source_ns, name, module_label
                             ) -> Optional[str]:
        """The hint for a reach `module_label` refuses under design 229, or
        None when this is an ordinary missing name."""
        if source_ns is None:
            return None
        origin = (source_ns.hidden_import(name)
                  or source_ns.hidden_import(name, as_module=True))
        if origin is None:
            return None
        return (f"`{name}` is imported by `{module_label}` but not re-exported "
                f"— add `public import` in `{module_label}`, or import "
                f"`{origin}` directly")

    def _report_not_reexported(self, source_ns, name, module_label, at) -> bool:
        """Report the refusal at `at` and return True, or return False when
        `name` is not one design 229 hides."""
        hint = self._not_reexported_hint(source_ns, name, module_label)
        if hint is None:
            return False
        self._error(
            ErrorKind.UNKNOWN_TYPE,
            f"`{name}` is not part of `{module_label}`'s surface",
            getattr(at, 'line', 0), getattr(at, 'column', 0),
            hint=hint)
        return True

    # ---------------------------------------------------------------- #
    # THE SELECTIVE-IMPORT SURFACE (DF-229a) — one funnel, six categories.
    #
    # `import m.{A, B}` on a USER module used to be a chain of
    # `if <found in table X>: bind` arms with no else, so a selected name that
    # matched no arm fell off the end and the import compiled clean with
    # nothing bound. std never had that hole: `_process_std_import` tests
    # membership in the leaf's precomputed name set BEFORE dispatching on
    # category, so it reports a missing name, and it reports it once.
    #
    # These two methods are that shape for a user module. `_selective_import_
    # entry` answers "what does this module bind under that name, and is it on
    # the surface"; `_module_selectable_names` is the `available:` list the
    # miss reports. Both walk ONE category tuple, so a category cannot be
    # coverable by the binder and invisible to the diagnostic (or the reverse,
    # which is how the type-alias arm came to be missing from both).
    #
    # ENTRY POINTS (obligation 1): `check_module`'s selective-import branch is
    # the only caller of the binder; the listing is additionally read by the
    # private-name report beside it. The GLOB branch does not funnel through
    # here — a glob names nothing, so it has no miss to report and iterates the
    # source tables directly.
    # ---------------------------------------------------------------- #

    # (kind word, how the source module binds a name of that kind). Order is
    # the dispatch order the arms had before the funnel: a name in two tables
    # resolves the way it always did.
    _SELECTIVE_IMPORT_CATEGORIES = ("struct", "enum", "function", "static",
                                    "trait", "type alias")

    @staticmethod
    def _lookup_selectable(source_ns, kind, name):
        """`source_ns`'s binding of `name` in category `kind`, or None.

        The TYPE categories ask the source module's own SPELLING view
        (design 255): an import names what the author wrote in braces, and the
        ordinary identity-first lookup answers with the merged std symbol
        whenever a std public name's identity is its spelling — so
        `import m.{File}` used to bind std's `File` rather than m's, silently."""
        if kind == "struct":
            return source_ns.lookup_own_struct(name)
        if kind == "enum":
            return source_ns.lookup_own_enum(name)
        if kind == "function":
            return source_ns.functions.get(name)
        if kind == "static":
            # A module-PRIVATE static lives in the per-module overlay rather
            # than the shared slot (DF-140h), so the private case is only
            # reachable by asking as the declaring module.
            return source_ns.get_static(name, tuple(source_ns.module_path))
        if kind == "trait":
            return source_ns.lookup_own_trait(name)
        if kind == "type alias":
            return source_ns.lookup_own_type_alias(name)
        return None

    def _selective_import_entry(self, source_ns, name):
        """`(kind, symbol)` for what `source_ns` binds under `name`, or None.

        Categories are tried in the fixed order above, so the answer is the one
        the pre-funnel dispatch would have reached."""
        for kind in self._SELECTIVE_IMPORT_CATEGORIES:
            sym = self._lookup_selectable(source_ns, kind, name)
            if sym is not None:
                return kind, sym
        return None

    def _selection_visible(self, sym, source_path, importer_module,
                           package_root) -> bool:
        """Whether an importer in `importer_module` may TAKE `sym` out of a
        module — the predicate for BOTH copying import forms.

        Design 229 answered PUBLIC-only, which made `import m.{X}` stricter
        than the qualified `m.X` it is sugar for: a `public(package)` name
        selected from INSIDE its own package was refused (DF-229c). The test is
        design 80's relation, asked with the importer as the accessor — so a
        package-visible name binds within the package and stays refused outside
        it, and `private` / `public(parent)` are unchanged.

        CALLERS: `check_module`'s SELECTIVE arm and its `available:` listing
        (`_module_selectable_names`), and — since DF-232k — its GLOB arm, which
        had kept the pre-229c PUBLIC-only test and so dropped exactly the names
        a sibling `import pkg.other.*` exists to pick up."""
        def_module = getattr(sym, 'def_module', ()) or tuple(source_path)
        return self._visibility_relation_allows(
            def_module, sym.visibility, importer_module, package_root)

    def _module_selectable_names(self, source_ns, builtin_namespace,
                                 source_path=(), importer_module=(),
                                 package_root=None):
        """Sorted names an importer may select out of `source_ns`.

        A module's surface is what it declares `public` plus what it
        `public import`s — never a name it merely imports (design 229), and
        never one of the builtins every namespace carries a copy of. The
        builtin filter is by symbol IDENTITY: `merge_into` shares symbol
        objects by reference, so a name whose symbol IS the builtin
        namespace's is one this module never declared.

        The visibility test is `_selection_visible`, the SAME predicate the
        binder uses, so the `available:` list can never omit a name the import
        would have bound (DF-229c made the two differ for a same-package
        importer)."""
        names = set()
        for kind in self._SELECTIVE_IMPORT_CATEGORIES:
            if kind == "function":
                candidates = list(source_ns.functions)
            elif kind == "static":
                candidates = list(source_ns.statics)
            else:
                # One spelling table backs all four type categories, and a
                # spelling that is not of THIS kind simply looks up as None.
                candidates = list(source_ns.type_names)
            for name in candidates:
                if name in names or source_ns.hidden_import(name) is not None:
                    continue
                sym = self._lookup_selectable(source_ns, kind, name)
                if sym is None or not self._selection_visible(
                        sym, source_path, importer_module, package_root):
                    continue
                if builtin_namespace is not None:
                    shared = self._lookup_selectable(builtin_namespace, kind,
                                                     name)
                    if shared is sym:
                        continue
                names.add(name)
        return sorted(names)

    def _available_hint(self, names) -> str:
        """std's `available:` line, for a module that may publish nothing."""
        if not names:
            return "it publishes no names"
        return "available: " + ", ".join(names)

    def _import_hiding(self, name: str, as_module: bool = False):
        """`(how this file spells the module, where the name really lives)` for
        a module THIS file imports that binds `name` without re-exporting it.

        The use-site half of design 229's diagnostic: the reader wrote a name
        that a module they can see does have, and needs to be told that seeing
        it is not reaching it. All THREE import shapes are searched — the
        whole-module form through `modules`, and the glob and selective forms
        through their own source lists, since neither binds a qualifier
        (DF-247b) and both would otherwise be unable to speak."""
        ns = self.namespace
        for qualifier, module_sym in ns.modules.items():
            source_ns = getattr(module_sym, 'namespace', None)
            if source_ns is None:
                continue
            origin = source_ns.hidden_import(name, as_module=as_module)
            if origin is not None:
                return (qualifier, origin)
        for label, source_ns in (list(getattr(ns, 'glob_sources', ()))
                                 + list(getattr(ns, 'selective_sources', ()))):
            origin = source_ns.hidden_import(name, as_module=as_module)
            if origin is not None:
                return (label, origin)
        return None

    def _nonbinding_qualifier_hint(self, name: str) -> Optional[str]:
        """The fixit for a qualifier this file did not bind, or None (DF-247b).

        THE ONE PLACE that turns "this name is not a qualifier here" into advice
        (obligation 1). ENTRY POINTS, the two positions a qualifier is written
        in: `_gate_resolved_type`'s qualified arm (a TYPE — `data.Data`), and
        `_check_identifier`'s undefined-variable ladder (an EXPRESSION —
        `data.Data()`, `time.Instant.now()`, `m.CONST`).

        Design 150's amendment made this reachable by taking the qualifier away
        from the selective form, so the common case is an author whose
        `import std.data.{Data}` used to reach the rest of the module for free.
        The fix is one line and nothing about the error would suggest it, so the
        hint names it. A qualifier no import in the file mentions at all gets
        the general form instead — that is a typo or a missing import, not a
        migration.
        """
        entry = getattr(self.namespace, 'nonbinding_qualifiers', {}).get(name)
        if entry is None:
            return None
        path, form = entry
        written = (f"`import {path}.*`" if form == "glob"
                   else f"`import {path}.{{...}}`")
        return (f"{written} binds the names it takes and no qualifier — add "
                f"`import {path}` to write `{name}.<name>`")

    def _names_a_type_here(self, name: str) -> bool:
        """Whether `name` already denotes a type in this module's own view."""
        ns = self.namespace
        if name in ns.directly_accessible:
            return True
        module = self._type_lookup_module()
        return any(lookup(name, module) is not None
                   for lookup in (ns.lookup_struct, ns.lookup_enum,
                                  ns.lookup_trait, ns.lookup_type_alias))

    def _report_bare_not_reexported(self, name: str, line: int,
                                    column: int) -> bool:
        """design 229 in a BARE position: the name is nowhere in this module's
        view, and a module it imports is the reason. Returns True (and reports)
        when that is what happened."""
        if self._names_a_type_here(name):
            return False
        found = self._import_hiding(name)
        if found is None:
            return False
        module_label, origin = found
        self._error(
            ErrorKind.UNKNOWN_TYPE,
            f"`{name}` is not part of `{module_label}`'s surface",
            line, column,
            hint=f"`{name}` is imported by `{module_label}` but not "
                 f"re-exported — add `public import` in `{module_label}`, or "
                 f"import `{origin}` directly")
        return True

    def _report_qualified_not_reexported(self, written, line: int,
                                         column: int) -> bool:
        """design 229 in a QUALIFIED position: `mid.Widget`, or a chain hop
        `mid.leaf.Widget`. Walks the qualifiers from this file's own view — the
        first hop is this module's business, every hop after it reaches THROUGH
        a module — and reports the first one the wall refuses."""
        parts = written.split('.')
        current_ns = self.namespace
        through_import = False
        for i, part in enumerate(parts):
            last = (i == len(parts) - 1)
            if through_import:
                origin = current_ns.hidden_import(part, as_module=not last)
                if origin is not None:
                    label = '.'.join(parts[:i])
                    self._error(
                        ErrorKind.UNKNOWN_TYPE,
                        f"`{part}` is not part of `{label}`'s surface",
                        line, column,
                        hint=f"`{part}` is imported by `{label}` but not "
                             f"re-exported — add `public import` in `{label}`, "
                             f"or import `{origin}` directly")
                    return True
            if last:
                return False
            module_sym = current_ns.modules.get(part)
            source_ns = getattr(module_sym, 'namespace', None)
            if source_ns is None:
                return False
            current_ns = source_ns
            through_import = True
        return False

    @staticmethod
    def _import_is_glob(imp) -> bool:
        """Whether `imp` is the `.*` form, in either spelling the parser uses."""
        return (bool(getattr(imp, 'is_glob', False))
                or list(getattr(imp, 'path', ()) or ())[-1:] == ['*'])

    @classmethod
    def _import_binds_qualifier(cls, imp) -> bool:
        """Whether this import FORM binds a module qualifier.

        THE ONE ANSWER (design 150 as amended by DF-247b, obligation 1). The
        WHOLE-MODULE form binds one — `import std.data` binds `data`, `as`
        renaming it — and NOTHING else does. The selective and glob forms bind
        exactly the surface they name and no qualifier.

        The amendment is the design's own reasoning applied consistently. A
        selective import is the form whose whole point is that the import LIST
        documents the dependency; handing it a qualifier for everything it did
        not list gave the file an undocumented reach into the rest of the module
        — the very thing the braces exist to prevent — and made `import m.{A}`
        and `import m` differ only in convenience. And a bonus reach was where
        DF-247b's fresh-identity bug hid: under a glob the same spelling
        resolved to a name-only type that compared unequal to the bare one, with
        nothing said.

        Callers: `_bind_module_qualifier` (which applies this, so no binding
        site can bypass it) and `_qualifier_is_reexported`.
        """
        return not cls._import_is_glob(imp) and not getattr(imp, 'symbols', None)

    @classmethod
    def _qualifier_is_reexported(cls, imp) -> bool:
        """Whether `imp` re-exports the qualifier it binds (design 229).

        Per FORM, not per `public` keyword. The WHOLE-MODULE form binds no bare
        name, so its qualifier is the only thing it has to hand on — that IS
        the re-export, and `public import dep` means an importer reaches dep's
        surface through the chain. The other two forms bind no qualifier at all
        (DF-247b), so a `public import m.{A}` hands on the names it NAMED and
        nothing else, which is what makes a curated facade possible."""
        return (bool(getattr(imp, 'is_public', False))
                and cls._import_binds_qualifier(imp))

    def _bind_module_qualifier(self, ns, imp, alias, path, source_ns):
        """Bind `alias` as a module qualifier in `ns` (design 150 pins 1, 3, 5).

        THE ONE BINDING SITE, and it applies `_import_binds_qualifier` itself
        rather than trusting its callers to (obligation 1: the decision has one
        home). ENTRY POINTS: `_process_std_import` for `std.*`, and
        `check_module`'s whole-module arm for a user module. Both used to have a
        selective-arm sibling; those are gone with the amendment, and a caller
        that grew one back would be refused here rather than quietly binding.

        A qualifier is one name bound to one module. Two imports claiming it is
        reported HERE, at the import, naming both paths — the use site could
        only say the qualifier reached the wrong module, which is the wrong
        place to learn it. Two imports of the SAME module never collide (the
        paths match), which is what makes `import std.data` beside
        `import std.data.{Data}` legal and complementary.

        The qualifier's VISIBILITY is what a reach from an importer is judged
        against, so it carries design 229's answer for this import's form
        (DF-232l: it used to be `PRIVATE` unconditionally — "an import is never
        re-exported", a comment design 229 superseded for the whole-module
        `public import` — which made the chain `facade.dep.f()` fail with
        "module `facade` has no symbol `dep`" for public symbols too, so the
        form re-exported NOTHING in value position)."""
        from namespace import ModuleSymbol
        if not self._import_binds_qualifier(imp):
            return
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
            visibility=(Visibility.PUBLIC
                        if self._qualifier_is_reexported(imp)
                        else Visibility.PRIVATE),
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
                # Design 249: THIS leaf's own declarations, by identity. The
                # `functions` representative is whichever module registered the
                # name first, so a name two std files own (`json.encode` beside
                # `cbor.encode`) would otherwise put the other file's function
                # behind this file's qualifier.
                own = builtin_namespace.lookup_module_function_overloads(
                    name, ("<std>", leaf))
                for sym in own:
                    view.register_function(name, sym)
                if not own:
                    fn = builtin_namespace.functions.get(name)
                    if fn is not None:
                        view.register_function(name, fn)
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
        # Design 218 unit 1: a std module may sit in a subdirectory, so the leaf
        # is the WHOLE tail after `std` (`std.compiler.frame` -> the module
        # `compiler.frame`, which is `std/compiler/frame.saw`). A single-segment
        # import is the same join over one element, so nothing else changes.
        leaf = '.'.join(path[1:])
        available = file_symbols.get(leaf)
        if available is None:
            self._error(
                ErrorKind.UNKNOWN_TYPE,
                f"unknown std module `std.{leaf}`",
                getattr(imp, 'line', 0), getattr(imp, 'column', 0),
                hint="std modules are: " + ", ".join(sorted(file_symbols)))
            return None

        # design 229: std is imported on the same terms as anything else — an
        # ordinary `import std.data` is this file's, and only `public import`
        # hands it on. The source path recorded is the one a reader would write.
        std_source = "std." + leaf
        is_public_import = bool(getattr(imp, 'is_public', False))

        def _expose(name, local):
            if not is_public_import:
                ns.note_private_import(local, std_source)
            # Register an aliased copy so the local name resolves to the symbol
            # (unaliased just un-gates the already-merged symbol).
            #
            # Design 249: FUNCTIONS come from THIS leaf's own declarations, by
            # identity, and the whole overload set comes with the name. The
            # `ns.functions` table below is keyed by bare name and holds
            # whichever module registered it first, so a name two std files own
            # (`json.encode` beside `cbor.encode`) bound the other file's
            # function under the alias.
            own_fns = (
                builtin_namespace.lookup_module_function_overloads(
                    name, ("<std>", leaf)) if local != name else [])
            if own_fns:
                import dataclasses
                for fn in own_fns:
                    # DF-187a: a function's namespace KEY is also its codegen
                    # name unless `mangled_name` says otherwise, so a second
                    # spelling needs the original carried as the mangled name.
                    # A COPY — mutating the shared std symbol would rename the
                    # definition out from under std itself.
                    if not getattr(fn, 'mangled_name', ""):
                        fn = dataclasses.replace(fn, mangled_name=name)
                    ns.register_bare_function(local, fn)
            elif local != name:
                for table, reg in (
                    (ns.structs, ns.register_struct),
                    (ns.enums, ns.register_enum),
                    (ns.functions, ns.register_function),
                    (ns.traits, ns.register_trait),
                    (getattr(ns, 'type_aliases', {}), getattr(ns, 'register_type_alias', None)),
                    (ns.statics, ns.register_static),
                ):
                    if name in table and reg is not None and local not in table:
                        sym = table[name]
                        # DF-187a: a FUNCTION's namespace KEY is also its codegen
                        # name unless `mangled_name` says otherwise, so binding
                        # the same symbol under a second spelling left codegen
                        # looking up `dt` and finding nothing
                        # (`Undefined function: dt`). Carry the original as the
                        # mangled name, which is exactly what the USER-module
                        # selective-import path already does — that is why the
                        # same rename over a user module worked and this did not.
                        # A COPY, because `_expose` is handing out the shared,
                        # already-merged std symbol: mutating it would rename the
                        # definition out from under std itself. Types need none
                        # of this — a type's codegen identity rides its symbol,
                        # not the key it was found under, which is why a renamed
                        # std TYPE always worked.
                        if table is ns.functions and not getattr(
                                sym, 'mangled_name', ""):
                            import dataclasses
                            sym = dataclasses.replace(sym, mangled_name=name)
                        reg(local, sym)
                        break
            ns.make_accessible(local)
            # Design 249: record WHICH std file this bare name came from. The
            # symbol is already here (the builtin namespace is merged wholesale
            # into every module), so this exposure registers nothing — and
            # without the binding, a name two std files own would resolve
            # against both of them from a file that imported one.
            if name in builtin_namespace.function_overloads:
                ns.bind_function_module(local, ("<std>", leaf))

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

        # Design 150 pin 1, as amended by DF-247b: the WHOLE-MODULE form binds
        # the last path segment as a qualifier (`as Y` overrides), and the
        # selective and glob forms bind none — they gave you the names.
        std_alias = getattr(imp, 'alias', None) or path[-1]
        # design 229's note is about what this file IMPORTS, not about what it
        # binds, so every form records it: `m.dep.X` from an importer is refused
        # by naming the private import, and that story is the same whether or
        # not `dep` also bound a qualifier over here.
        if not self._qualifier_is_reexported(imp):
            ns.note_private_import(std_alias, std_source, as_module=True)
        if self._import_binds_qualifier(imp):
            self._bind_module_qualifier(
                ns, imp, alias=std_alias,
                path=["std"] + path[1:],
                source_ns=self._std_leaf_namespace(leaf, builtin_namespace))
        else:
            # The two consumers a non-binding form still owes (DF-247b): the
            # per-file std leaf view, so a CONFORMANCE the leaf declares is
            # reachable exactly as it was through the qualifier, and the fixit
            # table, so `data.Data` under `import std.data.*` can be told which
            # line would make it mean something.
            ns.selective_sources.append(
                (std_source, self._std_leaf_namespace(leaf, builtin_namespace)))
            ns.nonbinding_qualifiers.setdefault(
                std_alias, (std_source, "glob" if is_glob else "selective"))
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
        # A name this module declares itself is the module's, at every position
        # and in any declaration order (see `_module_own_type_names`).
        if name in getattr(self, '_module_own_type_names', ()):
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
        # The qualifier a whole-module import binds is the LAST path segment, so
        # a dotted leaf (`compiler.frame`) offers `frame.Slot`, not
        # `compiler.frame.Slot` — the latter is not a spelling that resolves.
        qualifier = owner.rsplit('.', 1)[-1]
        self._error(
            ErrorKind.UNKNOWN_TYPE,
            f"`{name}` is not in the prelude and must be imported",
            line, column,
            hint=f"`import std.{owner}.{{{name}}}` selects it, "
                 f"`import std.{owner}.*` takes the module's whole vocabulary "
                 f"bare, and `import std.{owner}` lets you write "
                 f"`{qualifier}.{name}`",
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
    #   * `_register_trait` — a trait REQUIREMENT's parameter and return types,
    #     stored raw on the `TraitMethodSymbol` for the same reason and reached
    #     by nothing else (design 241 unit 1 added this fifth entry: an
    #     undefined type name in a requirement signature was silent).
    # The last four are declaration slots the compiler deliberately does not
    # resolve eagerly (a generic struct's `T`-typed field has nothing to resolve
    # against yet); they call the same walk with the same rule, so there is one
    # answer to "is this name gated", not five.
    #
    # Each of those four passes the DECLARATION's own type parameters as
    # `type_params`, because `current_type_params` describes the body being
    # checked and registration is not inside one.
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
    #   * `exempt_prelude_gate` -- the re-check after the coroutine transform
    #     reads an AST whose synthesized frames hold std types in fields.
    #   * `_in_synthesized_context` -- compiler-generated declarations.
    def _gate_written_type(self, written, depth: int = 0,
                           type_params=None,
                           is_type_argument: bool = False) -> None:
        """Run the prelude gate over every node of a WRITTEN type.

        The walk is needed because `_resolve_type` does not recurse into every
        composite it accepts — `UnsafePointer<T>` has no resolution arm at all —
        so a per-node check at the funnel's head would miss what the funnel
        itself never visits.

        `type_params` names the type parameters in force at this position, for
        the callers that know them better than `current_type_params` does — the
        four declaration-slot entries above. `None` means "read the ambient
        set", which is what the funnel proper wants.

        `is_type_argument` marks the DIRECT children of a `<...>` list, where a
        bare name may denote a design-148 const VALUE rather than a type
        (`Ring<CAP>` for a `static CAP: Int`). Deliberately not sticky: a
        `Vector<(Int, Nonesuch)>` puts `Nonesuch` in a tuple, not in the
        argument list, and it is a type name like any other.
        """
        if written is None or depth > 8:
            return
        # design 226 rides this walk for the `FuncPointer<F>` argument rule: it
        # visits every node of every written type from the same four entries,
        # which is exactly the quantifier that rule needs ("wherever a
        # `FuncPointer<...>` is written"). It runs BEFORE the exemption below
        # because the exemptions are about std's own SPELLINGS of gated names,
        # and say nothing about whether an `F` is a sync function type.
        self._check_funcpointer_arg(written)
        if not self._gate_exempt():
            self._gate_resolved_type(written, type_params, is_type_argument)
        for child in (written.inner_type, written.array_element_type,
                      written.func_return_type):
            self._gate_written_type(child, depth + 1, type_params)
        for child in (written.type_args or []):
            self._gate_written_type(child, depth + 1, type_params,
                                    is_type_argument=True)
        for child in ((written.element_types or [])
                      + (written.param_types or [])):
            self._gate_written_type(child, depth + 1, type_params)

    # ---------------------------------------------------------------- 226
    # `FuncPointer<F>` — what an `F` may be.
    #
    # `F` is a function TYPE and it must be `sync`. The two halves of that come
    # from two different places on purpose:
    #
    #   * FUNCTION-ness and `sync` are checked HERE, at the one walk every
    #     written type passes through, because a bare address has nowhere to
    #     keep the frame a suspending body runs out of — so a suspending `F` is
    #     wrong at the TYPE, before anything constructs one.
    #   * The design-136 rule (`unsafe` iff the signature names an unsafe type)
    #     is NOT re-checked here. `_validate_fn_type_effect` already recurses
    #     into `type_args`, so an `F` inside a `FuncPointer` written in any
    #     declared position reaches the existing check unchanged. Copying the
    #     rule would give one contract two implementations, which is what
    #     design 136 spent a unit removing.
    def _check_funcpointer_arg(self, t) -> None:
        """Judge ONE written type node against the `FuncPointer<F>` rule."""
        if (t is None or t.kind != TypeKind.STRUCT
                or t.struct_name != "FuncPointer"):
            return
        if not t.written_name:
            # A type the COMPILER built — resolution rebuilds every composite,
            # so the same annotation arrives here again with its provenance
            # stripped. The author wrote one spelling and owes one diagnostic;
            # judge the written node and let its rebuilt copies pass. Same rule,
            # same reason, as the prelude gate one method up.
            return
        args = t.type_args or []
        if len(args) != 1:
            self._funcpointer_error(
                t,
                f"`FuncPointer` takes exactly one type argument, but "
                f"{len(args)} were given",
                hint="write `FuncPointer<F>`, where `F` is a function type — "
                     "e.g. `FuncPointer<(Int) sync -> Int>`")
            return
        f = args[0]
        if self._funcpointer_arg_is_abstract(f):
            # A type PARAMETER standing in for `F`. Nothing is decided yet; the
            # instantiation is judged where its argument is written.
            return
        if f.kind != TypeKind.FUNCTION:
            self._funcpointer_error(
                t,
                f"`FuncPointer`'s type argument must be a function type, but "
                f"`{f}` is not",
                hint="write the signature the address has — e.g. "
                     "`FuncPointer<(Int) sync -> Int>`")
            return
        if not f.func_is_sync:
            self._funcpointer_error(
                t,
                f"`FuncPointer`'s type argument must be `sync`, but `{f}` may "
                f"suspend",
                hint="a suspending body runs out of a frame and a bare code "
                     "address has nowhere to keep one — write `sync` in the "
                     "effect slot (`(Int) sync -> Int`), or pass a `Task` handle "
                     "if the work really does suspend")

    def _funcpointer_signature(self, t):
        """`F` out of a `FuncPointer<F>`, or None when `t` is not one.

        THE ONE READER of the type's shape in the typechecker (design 226).
        The coercion funnel, both construction forms and the indirect-call path
        all ask here, so "is this a function pointer, and of what signature"
        has one answer and cannot drift between them. Returns None for a
        malformed one (an abstract or non-function `F`) — `_check_funcpointer_arg`
        has already reported those, and every caller wants the same "not a
        usable function pointer" answer.
        """
        if (t is None or t.kind != TypeKind.STRUCT
                or t.struct_name != "FuncPointer"):
            return None
        args = t.type_args or []
        if len(args) != 1:
            return None
        return args[0] if args[0].kind == TypeKind.FUNCTION else None

    def _funcpointer_arg_is_abstract(self, f) -> bool:
        """Is this `F` still a type PARAMETER rather than a chosen signature?

        A generic body may name `FuncPointer<F>` with its own `F` — builtin.saw's
        own extension does — and judging that spelling would reject the
        declaration that defines the type. An unresolved bare name is treated as
        a parameter: whatever it is, some other rule owns the name.
        """
        if f is None:
            return True
        if f.kind == TypeKind.TYPE_PARAM:
            return True
        if f.kind != TypeKind.STRUCT or not f.struct_name:
            return False
        name = f.struct_name
        if name in (getattr(self, 'current_type_params', {}) or {}):
            return True
        if self.get_struct_info(name) is not None:
            return False
        if self.get_enum_info(name) is not None:
            return False
        if self.namespace.lookup_type_alias(name) is not None:
            return False
        return True

    def _funcpointer_error(self, t, message: str, hint: str) -> None:
        """Report one `FuncPointer<F>` violation, once per written position."""
        line = t.written_line or getattr(t, 'line', 0) or 0
        column = t.written_column or getattr(t, 'column', 0) or 1
        key = (t.written_file, line, column, message)
        if key in self._funcpointer_reported:
            return
        self._funcpointer_reported.add(key)
        self._error(ErrorKind.TYPE_MISMATCH, message, line, column, hint=hint,
                    source_file=(t.written_file or None))

    def _gate_exempt(self) -> bool:
        """The three whole-pass exemptions the prelude gate honours.

        The transform's own is E5 (design 218a §6), and PERMANENT: a
        source-level rule in the same class as E3, since a synthesized frame
        holds `TaskGroup` and `Box` in fields no import mentions."""
        return bool(getattr(self, '_checking_builtins', False)
                    or getattr(self, 'exempt_prelude_gate', False)
                    or self._in_synthesized_context())

    def _gate_resolved_type(self, saw_type, type_params=None,
                            is_type_argument: bool = False) -> None:
        """Gate a type ARRIVING AT RESOLUTION, on its own written provenance.

        Anchors each report where the author wrote the NAME rather than at the
        enclosing declaration, and reports a given name-at-a-position once: the
        front half re-enters the same AST several times (the place lowering, the
        coroutine transform's re-check), and a rule that fires per resolution
        would print the same diagnostic three times.

        THREE QUESTIONS IN ONE ORDER, because each explains a name the one
        before it could not: is this a hidden std name (design 82/194), is it a
        name a module this file imports has and does not hand on (design 229),
        and — last, since either of those is a better answer where it applies —
        does it name a type at all (design 241 unit 1, DF-225b).

        The QUALIFIED arm asks its own two, in the same shape: design 229's
        export wall first, then — DF-247b — whether the qualifier is bound here
        at all. That second one used to be nobody's: an unresolvable qualifier
        left the written spelling alone, so `data.Data` became a name-only type
        that compared unequal to `Data` and the author was told about a type
        mismatch rather than about the import.
        """
        name = saw_type.written_name
        if not name:
            return
        if self._gate_exempt():
            return
        if '.' in name:
            # design 229 rides this funnel for the QUALIFIED spelling: the
            # prelude has nothing to say about `mid.Widget`, but the export wall
            # does, and every written type position passes through here.
            if self._vis_module_for_source(saw_type.written_file)[:1] == ("<std>",):
                return
            key = (saw_type.written_file, name,
                   saw_type.written_line, saw_type.written_column)
            if key in self._gate_reported:
                return
            self._gate_reported.add(key)
            if self._report_qualified_not_reexported(
                    name, saw_type.written_line, saw_type.written_column):
                return
            self._report_unbound_qualifier(saw_type, name)
            return
        key = (saw_type.written_file, name,
               saw_type.written_line, saw_type.written_column)
        if key in self._gate_reported:
            return
        self._gate_reported.add(key)
        # std's own declarations are REGISTERED inside a user compile — an
        # `import std.file.*` carries std.file's signatures along, and those name
        # `Path` bare because std files extend each other by design (design 82).
        # The IMPORT questions are about what a USER wrote, so they read the file
        # the spelling came from, exactly as `_decl_is_std_sourced` does for
        # member access. The undefined-type question below is NOT about imports
        # and asks itself of std too — a name std spells that denotes no type is
        # a typo wherever it sits (design 241 unit 1).
        if self._vis_module_for_source(saw_type.written_file)[:1] != ("<std>",):
            if self._std_name_gated(name, saw_type.written_line,
                                    saw_type.written_column):
                return
            # design 229: not a gated std name — but perhaps a name a module this
            # file imports has, and does not hand on.
            if self._report_bare_not_reexported(name, saw_type.written_line,
                                                saw_type.written_column):
                return
        # design 241 unit 1: nothing above explains the name, so ask whether it
        # names a type at all.
        self._report_undefined_type_name(saw_type, name, type_params,
                                         is_type_argument)

    def _report_unbound_qualifier(self, saw_type, name: str) -> None:
        """A qualified TYPE whose first hop is not a qualifier here (DF-247b).

        The design-150 amendment's refusal. Only the FIRST hop is judged: every
        hop past it reaches through a module, and a wrong name over there is
        design 229's diagnostic or the module's own "no such symbol", both of
        which have run by the time this is reached.

        THE SCOPE FENCE is the same one `_report_undefined_type_name` carries
        and for the same reason: a foreign module's signature reaches resolution
        whenever one of its declarations is instantiated, and it names ITS
        qualifiers, which are nothing here. Only the file being checked may be
        judged; its own nodes are judged when it is.
        """
        first = name.split('.')[0]
        if self._module_qualifier(first) is not None:
            return
        if self.namespace.modules.get(first) is not None:
            return
        here = self._decl_source_file or self._get_current_source_file()
        if not saw_type.written_file or saw_type.written_file != here:
            return
        # The refusal is the story; the mismatches this unresolved spelling
        # causes downstream are its shadow (DF-232o's rule, keyed on the whole
        # dotted name so the bare one beside it is untouched).
        self._unbound_qualifier_types.add(name)
        self._unbound_qualifier_files.add(saw_type.written_file)
        self._error(
            ErrorKind.UNKNOWN_TYPE,
            f"`{first}` is not a module qualifier here",
            saw_type.written_line, saw_type.written_column,
            hint=(self._nonbinding_qualifier_hint(first)
                  or f"a qualifier is bound by the whole-module import form — "
                     f"write `import <module>` to spell `{name}`"),
            source_file=(saw_type.written_file or None),
        )

    # ---------------------------------------------------------------- 241
    # AN UNDEFINED TYPE NAME (design 241 unit 1, closing DF-225b).
    #
    # A name in type position that resolves to nothing used to be one of two
    # silences. Where nothing downstream needed a layout it became an OPAQUE
    # nominal the checker carried, so an annotated `let` and a struct FIELD
    # reported a mismatch against a type that does not exist (``cannot assign
    # `Int` to variable of type `Nonesuch` ``, plus a "not `Printable`"
    # cascade); where a layout WAS needed it reached codegen and died there
    # (`internal compiler error: Undefined struct: Nonesuch`, with no location
    # at three of the five positions). Every other undefined-name kind — a
    # variable, a function, a struct literal's head, a module, a trait, an
    # attribute — already had a clean located diagnostic; types were the
    # exception.
    #
    # THE HARD PART is not detecting the name, it is knowing when NOT to. The
    # parser leaves every bare named type as a `STRUCT` node, so a type
    # PARAMETER and a typo are the same AST shape and only the surrounding
    # SCOPE tells them apart. So the rule fires from the design-194 funnel,
    # where the scope is known, and consults four things in turn:
    #   * the type parameters in force — `current_type_params` at the funnel
    #     proper, and the declaration's own list at the four registration
    #     entries, which run outside any body. Design 148 CONST parameters are
    #     in that list too: `[UInt8; N]` never reaches here (a length is an
    #     expression), but `FixedBuf<N>`'s argument does.
    #   * the names THIS UNIT declares (`_unit_type_names`) — registration is
    #     ordered and Saw is not, so a field naming an enum is judged three
    #     passes before that enum exists.
    #   * the namespace, which is imports plus everything already registered.
    #   * `Optional`, the one prelude spelling that is resolved rather than
    #     registered (`Optional<T>` IS `T?`, DF-174d) and so is in no table.
    # A name that survives all four is a name the program does not define.
    #
    # THE HINT is deliberately not a fuzzy match. The two diagnostics ahead of
    # this one in `_gate_resolved_type` already name the specific cause where
    # there is one — an unimported std name says which import to write, a name
    # a dependency hides says which module hides it — so what is left here is
    # genuinely "this name is nowhere", and the useful advice is the spelling
    # and the import, which is what DF-174d's own wording said.
    def _report_undefined_type_name(self, saw_type, name: str,
                                    type_params=None,
                                    is_type_argument: bool = False) -> None:
        """Report a bare written type name that denotes no type. One per
        written position; the caller's `_gate_reported` key does that."""
        here = self._decl_source_file or self._get_current_source_file()
        if not saw_type.written_file or saw_type.written_file != here:
            # THE SCOPE FENCE. A name's type parameters belong to the
            # DECLARATION that wrote it, and only a check running inside that
            # declaration has them. A foreign signature's node reaches
            # resolution here whenever one is instantiated — `m.lock({ ... })`
            # on std's `func lock<R>(&self, body: (&var T) sync -> R)` resolves
            # that `R` while checking the CALLER's body, where `R` is nothing —
            # so the only file this rule may judge is the one it is checking.
            # (The same node is judged, correctly, when its own file is.)
            return
        if self._type_name_is_defined(name, type_params):
            return
        if is_type_argument and self._names_a_const_static(
                name, saw_type.written_file):
            # design 148/DF-172j: a const generic ARGUMENT written as a bare
            # name (`Ring<CAP>`). `_fold_const_type_args_in_program` turns it
            # into a value, but it runs AFTER the registration passes this
            # funnel fires from — it needs the referenced type's parameter list
            # to tell a const argument from a type one — so the node still
            # reads as a named type here. A wrong-kind argument is that pass's
            # diagnostic, and it names the parameter.
            return
        self._error(
            ErrorKind.UNKNOWN_TYPE,
            f"undefined type `{name}`",
            saw_type.written_line, saw_type.written_column,
            hint=self._retired_type_hint(name)
                 or "check the spelling, and that the module defining it is "
                    "imported",
            source_file=(saw_type.written_file or None),
        )

    # THE RETIRED TYPE NAMES — one table, one helper, on the model of
    # `_RETIRED_TRAIT_HINTS` (design 219 unit B4). A name the language used to
    # define and no longer does deserves better than "undefined type": the
    # author wrote something that WAS correct, and the fix is a word. Every
    # written type position routes through the ONE funnel above, so the hint
    # cannot appear at some positions and not others.
    _RETIRED_TYPE_HINTS = {
        "TaskHandle": "`TaskHandle<T>` is `Task<T>` (design 242) — the "
                      "cooperative engine owns the `Task` vocabulary now, and "
                      "`Thread<T>` is what `Thread.spawn` hands back",
        "VoidTaskHandle": "`VoidTaskHandle` is `VoidTask` (design 242)",
    }

    def _retired_type_hint(self, name):
        """The teaching hint for a type name the language retired, or None."""
        return self._RETIRED_TYPE_HINTS.get((name or "").rsplit('.', 1)[-1])

    def _type_name_is_defined(self, name: str, type_params=None) -> bool:
        """THE DECISION PROCEDURE behind the diagnostic above."""
        if name == "Optional":
            # `Optional<T>` is a SPELLING of `T?`, resolved in `_resolve_type`
            # and registered nowhere (DF-174d).
            return True
        params = (type_params if type_params is not None
                  else getattr(self, 'current_type_params', None) or {})
        if name in params:
            return True
        if name in getattr(self, '_unit_type_names', ()):
            return True
        return self._names_a_type_here(name)

    def _names_a_const_static(self, name: str, written_file) -> bool:
        """Does `name` denote a module `static` this unit indexed (DF-172j)?

        Reads `_collect_const_statics`' table, which is built before any
        registration pass and keyed by (defining module, name) — so the answer
        is the one the const-argument fold will give, asked from the file the
        spelling came from."""
        table = getattr(self, '_const_static_decls', None) or {}
        module = self._vis_module_for_source(written_file)
        return (module, name) in table

    def _declared_type_param_names(self, decl) -> set:
        """The type parameters a DECLARATION brings into scope, const ones
        included — what the four registration entries pass to the funnel."""
        return {tp.name for tp in (getattr(decl, 'type_params', None) or [])}

    def _collect_unit_type_names(self, program) -> None:
        """Stamp `_unit_type_names` for one compilation unit's AST.

        Runs before any of the declarations is registered — see the field's
        comment. The associated-type names ride along because a trait's `type
        Item` and an extension's `type Item = Int` both make `Item` a name that
        denotes a type somewhere in the unit, and neither lands in any type
        table."""
        names = set()
        for group in (getattr(program, 'type_definitions', ()) or (),
                      getattr(program, 'structs', ()) or (),
                      getattr(program, 'enums', ()) or (),
                      getattr(program, 'traits', ()) or ()):
            for d in group:
                names.add(d.name)
        for trait in (getattr(program, 'traits', ()) or ()):
            for at in (getattr(trait, 'associated_types', None) or ()):
                names.add(at.name)
        for ext in (getattr(program, 'extensions', ()) or ()):
            for assign in (getattr(ext, 'type_assignments', None) or ()):
                names.add(assign.name)
        self._unit_type_names = names

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
        current method or function context, then from the module being checked
        (DF-243b — see `_diagnostic_source_file`).

        design 218 unit 1.5 §3: while an INSTANCE is being checked, every error
        carries the instantiation note. Attached here rather than at the
        hundreds of `_error` call sites, which is the only way the rule can be
        total — a diagnostic written next year gets it too.
        """
        if self._instance_muted:
            return          # abstract-first — see `_checking_instance`
        if source_file is None:
            source_file = self._diagnostic_source_file()
        self.reporter.error(kind, message, line, column, hint, source_file,
                            note=self._mono_instance_note())

    def _warning(self, kind: ErrorKind, message: str, line: int, column: int,
                 hint: Optional[str] = None, source_file: Optional[str] = None,
                 category: Optional[str] = None):
        """Report a warning with automatic source file detection. A `category`
        names a `-W` opt-in (design 150); without one the warning is
        unconditional."""
        # PROVENANCE SKIP (design 218c §1c) — THE DESIGN-150 WARNING CATEGORIES.
        # A warning is a remark about what an author WROTE, and nothing in a
        # monomorphized instance was written: every type there arrived by
        # substitution, and the template's own text was judged where the author
        # put it. The one category that exists, `shadowed-qualifier`, is the
        # worked example — it fires at a DECLARATION, and the instance's
        # declarations are clones. Named per-rule at the funnel because the
        # whole warning system is one row of §1c's list.
        if self._mono_instance is not None:
            return
        if source_file is None:
            source_file = self._diagnostic_source_file()
        self.reporter.warning(kind, message, line, column, hint, source_file,
                              category=category)

    # ------------------------------------------------------------------ #
    # design 218 unit 1.5 — checking a MONOMORPHIZED INSTANCE.
    #
    # An instance is a clone of a template with the type arguments substituted
    # in. It keeps the template's source spans, so a diagnostic it raises
    # anchors at the author's own line — right, and by itself silent about
    # which of the instantiations is the broken one. `_checking_instance` names
    # that, and it is also the flag the §1c PROVENANCE SKIPS read: a rule about
    # what an author WROTE does not apply to code that arrived by
    # substitution. Every skip is written at its own rule with its own reason;
    # a new checker rule defaults to RUNNING, which is what makes the list
    # auditable.
    # ------------------------------------------------------------------ #

    @contextmanager
    def _checking_instance(self, display: str, demand: Optional[str] = None,
                           substituted_params=(), substituted_return=False):
        """Check one instance. `display` is its source spelling
        (`launder<Res>`); `demand` is where the first demand for it came from.
        `substituted_params` names the by-value parameters whose declared type
        arrived by substitution — §1c skip 4's input, computed once at the
        clone rather than re-derived at every transfer — and
        `substituted_return` is skip 5's, the same question at the return.
        Nests: an instance's body may itself demand another.

        ABSTRACT-FIRST (design 218c §3): an instance is only worth reporting in
        a compile the abstract layer ACCEPTED. Every template body in every
        module is checked before the first instance is built, so a reporter
        that already holds an error holds the BETTER one — at the definition or
        the call, anchored on what the author wrote — and everything the
        instance then derives from the same fault is noise. Two corpus tests
        assert an exact error COUNT and found this immediately.
        `_instance_muted` is that decision, taken once per instance and read at
        the `_error` funnel; it is not a return to deleting diagnostics, which
        threw away the instance's verdict even when the compile was otherwise
        clean.
        """
        previous = self._mono_instance
        previous_muted = self._instance_muted
        previous_params = self._mono_substituted_params
        previous_return = getattr(self, '_mono_substituted_return', False)
        self._mono_instance = (display, demand)
        self._mono_substituted_params = frozenset(substituted_params)
        self._mono_substituted_return = bool(substituted_return)
        self._instance_muted = (previous_muted
                                or not INSTANCE_ERRORS_ARE_REAL
                                or self.reporter.has_errors())
        try:
            yield
        finally:
            self._mono_instance = previous
            self._instance_muted = previous_muted
            self._mono_substituted_params = previous_params
            self._mono_substituted_return = previous_return

    def _mono_instance_note(self) -> Optional[str]:
        if self._mono_instance is None:
            return None
        display, demand = self._mono_instance
        if demand:
            return f"in the instantiation `{display}`, required from {demand}"
        return f"in the instantiation `{display}`"

    def _in_mono_instance(self) -> bool:
        """Whether a §1c provenance skip applies here. Read it at ONE rule with
        a comment saying which, never as a general permission."""
        return self._mono_instance is not None

    # ------------------------------------------------------------------ #
    # §1c SKIPS 3 AND 4 — the two ARTIFACT-OF-RECHECK predicates (design
    # 218c's A3 OUTCOME, lead-signed at the stage-3c dispatch).
    #
    # Stage 3c materializes and checks EVERY registered instance in every
    # compile (the Sep-1 splice-all ruling), so std's own type closure is
    # re-judged on `hello.saw`. Twenty-four diagnostics survived that, over
    # code the corpus compiles and RUNS, and the triage put them in three
    # families. Two of the families are these predicates; the third turned out
    # to be a CASCADE of the first and needed no rule of its own (see
    # `_mono_copy_is_a_retain`).
    #
    # Each is a NAMED question asked at exactly ONE rule, with the rule's own
    # comment saying which and why — never a blanket "is this an instance"
    # suppression, and never keyed on "is this std". A new checker rule
    # defaults to RUNNING, which is what keeps the list auditable.
    # ------------------------------------------------------------------ #

    def _mono_copy_is_a_retain(self, obj_type) -> bool:
        """§1c SKIP 3 — a `.copy()` the SILENT tier answers, on a clone.

        The `.copy()` receiver test asks for a `copy` METHOD, or a trivially
        copyable type. A `String` is neither: it is on the silent Copy tier,
        where a copy is a refcount bump codegen emits with no method to look
        up. In an AUTHORED body that refusal is right — `s.copy()` on a local
        `String` is a real error today, because nothing there said a copy was
        wanted. In a substituted clone the spelling is not the author's choice
        at this type: the template wrote `buf[i].copy()` under a declared
        `<T: ExplicitCopy>` bound, which is design 219's licence for the
        spelling, and every Copy type satisfies that bound. The abstract layer
        judged it once, the call site discharged the bound against the concrete
        argument, and codegen lowers the element copy BY TIER — which is why
        `Vector<String>.copy()` compiles and runs today and the re-check is the
        only thing that disagrees.

        Six of the twenty-four: `Vector`/`Map` `.copy`/`.try_copy` at a
        `String` key or element, and `VectorIterator`/`EnumeratedIterator`
        `.next`.

        BOTH HALVES OF THE SILENT TIER, which is what design 219 unified and
        what the Sep-1 census's class 2 residue was: `'free'` (bitwise) as well
        as `'implicit'` (refcounted). The predicate read `== 'implicit'` and
        left `Vector<UnsafePointer<Int8>>.copy` refused — a raw pointer copies
        by being copied, so its `.copy()` has no method to look up for exactly
        the reason a `String`'s has none. Which of the two a type uses is a
        codegen detail no rule above it sees, so a skip that distinguishes them
        is drawing a line the tier does not have.
        """
        if self._mono_instance is None:
            return False
        return self.namespace.copy_tier(obj_type) in ('free', 'implicit')

    def _transfer_is_substituted_param(self, expr) -> bool:
        """§1c SKIP 4 — a transfer of a by-value parameter whose type arrived
        by substitution.

        In the template that parameter's type is a type PARAMETER, so
        `copy_tier` answers `'abstract'` and the transfer takes design 219 wave
        C's arm: it RAISES A REQUIREMENT on the parameters it names, and every
        call site discharges that requirement against its concrete argument.
        The abstract layer therefore has a judgment for this position already,
        and it is the one that fits — per PATH, so a body that forwards its
        parameter once (`buf[i] = value`, `self.swap_out(i, value)`) duplicates
        nothing and requires nothing. Asking the concrete tier again on the
        clone is a SECOND, coarser judgment of the same transfer, and it
        refuses bodies whose call sites the first judgment already cleared.

        Sixteen of the twenty-four: `Vector.set`/`push`/`swap_out` and
        `Arc.init` at every non-Copy element the corpus instantiates.

        Narrow on purpose. It fires only for an `Identifier` naming a by-value
        parameter of the instance's OWN signature whose declared type named a
        substituted type parameter — computed at the clone, in
        `monomorphize.substituted_param_names`. A local, a field read, a place
        read and a parameter of a written concrete type are all re-judged
        exactly as they were.

        WHAT SUPPLIES IT (obligation 1 — `substituted_param_names` is the one
        funnel, and these are its entry points): `monomorphize`'s
        materialization funnel and the four design-70/74 builders in
        `effects.py`, each of which holds the pristine template and the type
        map at the moment it clones. The one `_checking_instance` that supplies
        NOTHING is `check_module`'s re-check of an ALREADY-SPLICED instance:
        the template is gone by then, so the answer cannot be re-derived
        there. That path re-reads a body whose splicing check already reported,
        and stage 3c-2's single materialization funnel is what removes the
        second reading rather than teaching it the skip.
        """
        if self._mono_instance is None or not self._mono_substituted_params:
            return False
        return (isinstance(expr, Identifier)
                and expr.name in self._mono_substituted_params)

    def _mono_result_role(self, value_expr) -> Optional[str]:
        """`'ok'` / `'err'` for a returned PARAMETER whose role design 30's
        generic lock-in fixed abstractly, or None.

        Read at `_autowrap_into_result` and nowhere else. The map is
        `mono_result_roles`, stamped on the clone by
        `monomorphize.result_roles` from the TEMPLATE's own annotations — the
        one place the abstract spellings still exist once an instantiation has
        made `T` and `E` the same type.
        """
        if not isinstance(value_expr, Identifier):
            return None
        for decl in (self.current_method, self.current_function):
            roles = getattr(decl, 'mono_result_roles', None)
            if roles:
                return roles.get(value_expr.name)
        return None

    def _mono_return_is_substituted(self) -> bool:
        """§1c SKIP 5 — a RETURN-POSITION judgment whose return type arrived by
        substitution. The named sibling of skip 4's parameter rule (Amendment
        B2), and the census's single largest class.

        The argument is skip 4's, one position over. In the template the return
        type is a type PARAMETER, so every return-position rule that depends on
        what the type IS was answered ABSTRACTLY — design 24's decidability
        rule defers what it cannot decide, design 219 wave C raises a
        requirement each call site discharges, and design 30's own ambiguity
        refusal argues in its docstring that the abstract per-parameter wrap
        decision is what every instantiation must inherit. Re-asking the
        concrete question on the clone is a SECOND, coarser judgment of a
        transfer the first one already cleared.

        WHAT IT COVERS, by census class
        (`designs/reviews/splice-census-sep1.md` §5):

          * class 1, 7,750 raw records in 1,538 of 1,617 programs — the
            `borrows` LOWERING's own clones. `place_transform` rewrites every
            accessor into a method-generic over its window result type `__R`
            returning `__R`, and at the overwhelmingly common statement-position
            window `__R = Void`, so the clone is a `-> Void` body whose
            `return __window(...)` is refused as returning a value. Twelve of
            them are USER accessors, not std's.
          * classes 17 and 18 (DF-286b class 6 and its std twin) — a NoCopy
            return without `move`, at `run_and_return<Res>` and
            `Map._take_value`. Conformance row V47 pins the first program
            LEGAL.
          * classes 11 and 13 — the ambiguous Result auto-wrap, which exists
            only because an instantiation made the Ok and Err types coincide.

        NOT a blanket return-position suppression: a body whose declared return
        type names NO type parameter is re-judged exactly as it was, which is
        every concretely-typed return in every instance.
        """
        return self._mono_instance is not None and self._mono_substituted_return

    def _no_move_is_fresh_journey(self, var_info) -> bool:
        """design 188's FRESH-JOURNEY rule — USER-RULED Sep 2 (218c B4).

        Design 188 said a `NoMove` value moves exactly once, "constructor into
        binding". It now says **moves exactly once, INTO ITS HOME**: a by-value
        PARAMETER of the enclosing function may be placement-moved
        (`ptr[i] = move param`) at a `NoMove` type, PROVIDED the body took no
        reference to the parameter before the placement.

        WHY THAT IS SOUND, and why it blesses nothing broader. The caller-side
        rules already fence it: a BOUND `NoMove` value cannot be moved into an
        argument (that is this same refusal, at the call), so a `NoMove`
        by-value parameter is always a FRESH TEMPORARY — constructed in the
        argument expression, handed straight over, its address never
        observable. The journey construction -> parameter -> placement is one
        continuous trip to the value's first and only home, which is exactly
        what "moves once" was ever about. Take a reference to the parameter
        first and the address WAS observable, so the trip is over and the
        refusal stands.

        WHAT IT BLESSES: `Box<T, A>.make`'s `ptr[0] = move value`, verbatim.
        Design 188's own documented idiom is "hold a NoMove value behind a Box
        for a movable handle over pinned storage", and the census found that
        idiom's construction path unwritable as concrete code —
        `examples/nomove_tier.saw` calls `Box<Anchor>.make` and RUNS only
        because nothing had ever instance-checked the generic.

        WHAT IT DOES NOT BLESS: a `Vector<NoMove>`. Its `push` relocates on
        realloc, so its instance-check refusal STANDS as correct containment —
        the rule is about a placement into freshly allocated storage the value
        then lives in, not about a slot a later growth will move.

        THE THREE CONDITIONS, each necessary:
          1. a placement write is in flight — the RHS of `ptr[i] = ...` through
             a MUTABLE pointer, which is the only expression in the language
             that writes into uninitialized storage;
          2. the moved binding is a by-value PARAMETER of the enclosing
             function or method (a local was BOUND, and a binding is a home);
          3. no `&`/`&var` has named that binding.
        """
        return (self._placement_move_target
                and var_info is not None
                and getattr(var_info, 'is_parameter', False)
                and var_info.binding_id not in self._referenced_bindings)

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

        # design 241 unit 1: the names this unit declares, before the ordered
        # registration passes below start judging references to them.
        self._collect_unit_type_names(program)

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

        # DF-194b: now that enums exist, refuse an alias that names one. The
        # alias pass above runs first (an alias RHS may name a type registered
        # after it), so this is the earliest point at which the question has an
        # answer. Entry point 1 of 2 — see `_reject_enum_underlying_aliases`.
        self._reject_enum_underlying_aliases(program)

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

        # "A public API needs public types" (user ruling, Aug 21): no
        # declaration names a type less visible than its own effective reach.
        # Here because every type is registered (so a name has a tier) and the
        # identities are canonical, and after the bound validator so a bound
        # that names no trait at all is already its own diagnostic.
        self._check_signature_visibility_in_program(program)

        # design 246 Unit A: a type whose storage contains its own storage
        # INLINE has no finite layout. Ahead of the containment checks so the
        # first thing an infinite-size declaration is told is that it has no
        # size — the copy-policy question about a member it cannot lay out is
        # a consequence, not the finding. Entry point 1 of 2; see
        # `_check_recursive_type_sizes`.
        self._check_recursive_type_sizes(program)

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
        self._check_main_return_type(program)

        # Amendment A1 (DF-285b): the two capture points `check_module` has,
        # here too — because THIS is the path std goes through, and stage 3's
        # instance check needs a pristine template to clone and the template's
        # home module scope to check the clone in. Both are cheap enough to pay
        # here precisely because `build_builtin_namespace`'s result is cached:
        # the snapshot is taken once per cache BUILD and restored by
        # `pickle.loads` on every compile after it.
        self._capture_pristine_templates(program)
        # Design 82 makes each std FILE its own module, and
        # `_vis_module_for_source` is already the authority on which — so the
        # per-file record is that answer paired with the namespace these bodies
        # are about to be checked in. Recorded BEFORE the body checks for the
        # same reason the snapshot is: nothing in the loops below may observe a
        # half-filled store.
        for _src in _module_source_files(program):
            # DF-289a: FIRST claim wins — see `_module_source_files`.
            self._module_scope_by_file.setdefault(
                _src, (self._vis_module_for_source(_src), self.namespace))

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

        # design 219 wave C: discharge every recorded generic tier obligation.
        # After every body, because declaration order is not call order, and to
        # a fixpoint, because a requirement propagates through forwarding hops.
        self._tier_discharge_all()

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
        # design 226: a `FuncPointer<F>` IS a C function pointer — one machine
        # word, no environment beside it — so it marshals exactly as an
        # `UnsafePointer<T>` does. This is what makes the C-callback shape
        # expressible in both directions: an `@export`ed Saw function may
        # RECEIVE a callback, and an offloaded extern may be handed one.
        if self._funcpointer_signature(resolved) is not None:
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
        # DF-232j: every namespace that can be reached through a qualifier
        # decides `public(package)` itself, so every one of them carries the
        # package names. The compile-start authority is this checker's own set
        # (`--module-path`), not the cached builtin namespace.
        ns.mapped_packages = frozenset(self.mapped_packages)
        # DF-232n: and the package identities, which decide the same question
        # for every module that arrived by relative path.
        ns.package_identities = self.package_identities

        # Clone builtins into this module's namespace (all directly accessible)
        ns.merge_into(builtin_namespace)
        ns.directly_accessible = set(builtin_namespace.directly_accessible)
        # Design 255: everything the merge just bound is AMBIENT — the prelude
        # core, plus the std names design 82 Part B keeps behind an import gate.
        # Recorded here, before any import or declaration of this module runs,
        # so `bind_type_name` can tell an ambient binding from one this file
        # made. Both facts it needs come from this moment: the label (which std
        # file, and whether the name is in scope unwritten) and the membership.
        ns.note_builtin_type_bindings(builtin_namespace)

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
                    # DF-242b: the whole overload set, not the representative —
                    # binding one member is what made a call only a sibling
                    # matches report a type error about a candidate the author
                    # never meant.
                    for over in parent_namespace.lookup_function_overloads(name):
                        if over.visibility == Visibility.PUBLIC:
                            ns.register_bare_function(name, over)
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

        # Design 254: the module-level `public import` edges this file declares.
        # EVERY form contributes one — `public import m.{A}` re-exports a single
        # NAME but forwards m's extension scope whole, mirroring how a selective
        # DIRECT import already brings the whole module's extensions. Recorded
        # here, at the same four points the direct import is; what the edges MEAN
        # is `_close_over_public_imports`' business, below the loop.
        public_edges: Set[Tuple[str, ...]] = set()

        def _note_direct(imp, target):
            """Record `target` as a direct import of this file (design 142), and
            as a `public import` edge when the line said so (design 254)."""
            direct_imports.add(target)
            if getattr(imp, 'is_public', False):
                public_edges.add(target)

        # Design 229: what an ordinary import binds here is this module's own
        # business. `_note_import` records each binding against the path it came
        # from unless the line said `public import`, and `Namespace.
        # hidden_import` is what every reach from an importer then consults.
        def _note_import(imp, name, source, as_module=False):
            if not getattr(imp, 'is_public', False):
                ns.note_private_import(name, source, as_module=as_module)

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
                    _note_direct(imp, ("<std>", std_leaf))
                continue

            if imp.is_glob:
                # import foo.* -> copy all public symbols to local namespace
                base_path = imp_path[:-1] if imp_path and imp_path[-1] == '*' else imp_path
                _note_direct(imp, base_path)
                if base_path in checked_modules:
                    source_ast, source_ns = checked_modules[base_path]
                    glob_label = '.'.join(base_path) if base_path else "<entry>"
                    ns.glob_sources.append((glob_label, source_ns))
                    # DF-247b: a glob has never bound a qualifier, and the
                    # spelling used to resolve to a name-only type anyway. Say
                    # which line would bind one instead.
                    if base_path:
                        ns.nonbinding_qualifiers.setdefault(
                            base_path[-1], (glob_label, "glob"))
                    # Design 229: the glob takes the module's SURFACE — what it
                    # declares public plus what it re-exports — never a name it
                    # merely imports.
                    #
                    # DF-232k: and it takes what the IMPORTER is entitled to,
                    # not what is `public` full stop. `_selection_visible` is
                    # the same accessor-aware predicate the selective arm asks
                    # (DF-229c fixed that arm; this one kept the pre-229c
                    # shape), so a sibling glob inside a package binds the
                    # package's `public(package)` names and an outside glob
                    # keeps excluding them — one predicate, no special case for
                    # either direction.
                    def _glob_takes(nm, sym, _path=base_path):
                        return (source_ns.hidden_import(nm) is None
                                and self._selection_visible(
                                    sym, _path, tuple(module_path or ()),
                                    ns.package_root))
                    for name, ident, sym in source_ns.iter_structs():
                        if _glob_takes(name, sym):
                            ns.register_struct(name, sym, source_label=glob_label)
                            ns.make_accessible(name)
                            _note_import(imp, name, glob_label)
                            _import_conformances(ident, ident, source_ns)
                    for name, ident, sym in source_ns.iter_enums():
                        if _glob_takes(name, sym):
                            ns.register_enum(name, sym, source_label=glob_label)
                            ns.make_accessible(name)
                            _note_import(imp, name, glob_label)
                            _import_conformances(ident, ident, source_ns)
                    for name, sym in source_ns.functions.items():
                        if _glob_takes(name, sym):
                            # DF-242b: the whole overload set, judged member by
                            # member (an overload may be `public(package)` while
                            # its sibling is `public`).
                            for over in source_ns.lookup_function_overloads(name):
                                if _glob_takes(name, over):
                                    ns.register_bare_function(name, over)
                            ns.make_accessible(name)
                            _note_import(imp, name, glob_label)
                    for name, _ident, sym in source_ns.iter_traits():
                        if _glob_takes(name, sym):
                            ns.register_trait(name, sym, source_label=glob_label)
                            ns.make_accessible(name)
                            _note_import(imp, name, glob_label)
                    for name, sym in source_ns.statics.items():
                        if _glob_takes(name, sym):
                            if name not in ns.statics:
                                ns.register_static(name, sym)
                            ns.make_accessible(name)
                            _note_import(imp, name, glob_label)
            elif imp.symbols:
                # import foo.{A, B} -> copy specific symbols to local namespace
                _note_direct(imp, imp_path)
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
                        # DF-229c: the visibility question is asked with THIS
                        # module named as the accessor, so the answer matches
                        # the qualified `m.X` path's.
                        def _sel_names(_ns=source_ns, _path=imp_path):
                            return self._module_selectable_names(
                                _ns, builtin_namespace,
                                source_path=_path,
                                importer_module=tuple(module_path or ()),
                                package_root=ns.package_root)
                        # Design 229: selecting a name the source module only
                        # imports is refused HERE, at the import, where the fix
                        # (either fix) can be stated.
                        if self._report_not_reexported(
                                source_ns, sym_name, sel_label, imp):
                            continue
                        # DF-229a: what the module binds under this name, asked
                        # ONCE, before any category dispatch — std's shape. The
                        # two ways a selection can fail are reported here rather
                        # than falling off the end of the arms below, which is
                        # what let `import m.{NoSuchThing}` compile clean.
                        entry = self._selective_import_entry(source_ns, sym_name)
                        if entry is None:
                            self._error(
                                ErrorKind.UNKNOWN_TYPE,
                                f"`{sym_name}` is not defined in `{sel_label}`",
                                getattr(imp, 'line', 0),
                                getattr(imp, 'column', 0),
                                hint=self._available_hint(_sel_names()))
                            continue
                        sel_kind, sym = entry
                        if not self._selection_visible(
                                sym, imp_path, tuple(module_path or ()),
                                ns.package_root):
                            self._error(
                                ErrorKind.UNKNOWN_TYPE,
                                f"`{sym_name}` is "
                                f"{self._vis_word(sym.visibility)} in "
                                f"`{sel_label}`",
                                getattr(imp, 'line', 0),
                                getattr(imp, 'column', 0),
                                hint=f"mark it `public` in `{sel_label}` to "
                                     f"expose it; "
                                     + self._available_hint(_sel_names()))
                            # DF-232o: the name is refused, so every use of it
                            # below resolves to an opaque same-named type and
                            # disagrees with the real one at each one. This
                            # refusal is the cause; poison the name so its
                            # shadow is not reported again per use.
                            if sel_kind in ("struct", "enum", "trait",
                                            "type alias"):
                                self._poison_refused_type_name(local)
                            continue
                        _note_import(imp, local, sel_label)
                        if sel_kind in ("struct", "enum", "trait", "type alias"):
                            register = {
                                "struct": ns.register_struct,
                                "enum": ns.register_enum,
                                "trait": ns.register_trait,
                                "type alias": ns.register_type_alias,
                            }[sel_kind]
                            register(local, sym, source_label=sel_label)
                            ns.make_accessible(local)
                            if sel_kind in ("struct", "enum"):
                                _ident = source_ns.resolve_type_identity(sym_name)
                                _import_conformances(_ident, _ident, source_ns)
                        elif sel_kind == "function":
                            # DF-242b: selecting a name selects the whole
                            # overload set it stands for, member by member.
                            # For an ALIASED function, bind a copy whose
                            # codegen name is the real symbol (design 53), so
                            # a call under the alias reaches the real
                            # definition. Unaliased imports are unchanged.
                            for over in source_ns.lookup_function_overloads(
                                    sym_name):
                                if not self._selection_visible(
                                        over, imp_path,
                                        tuple(module_path or ()),
                                        ns.package_root):
                                    continue
                                if local != sym_name and not over.mangled_name:
                                    import dataclasses
                                    over = dataclasses.replace(
                                        over, mangled_name=sym_name)
                                ns.register_bare_function(local, over)
                            ns.make_accessible(local)
                        else:
                            if local not in ns.statics:
                                ns.register_static(local, sym)
                            ns.make_accessible(local)
                    # DF-247b's amendment to design 150 pin 3: the selective
                    # form binds the names it SELECTED and NO qualifier. The
                    # import list is what documents the dependency, and a bonus
                    # reach into everything the list did not name is the
                    # undocumented dependency the braces exist to prevent.
                    #
                    # Two things the form still owes, neither of which is the
                    # qualifier: design 229's private-import note (an importer
                    # asking for `m.dep.X` is refused by naming what `m`
                    # imports, whoever binds what), and the source namespace as
                    # a COHERENCE search root (design 142 makes a conformance
                    # program-wide, so no import form may lose one — DF-238c
                    # closed the glob's copy of this hole).
                    sel_alias = (imp.alias or (imp.path[-1] if imp.path else ""))
                    sel_source = '.'.join(imp_path) if imp_path else "<entry>"
                    ns.note_private_import(sel_alias, sel_source,
                                           as_module=True)
                    ns.selective_sources.append((sel_source, source_ns))
                    ns.nonbinding_qualifiers.setdefault(
                        sel_alias, (sel_source, "selective"))
            else:
                # import foo.bar -> register module for qualified access
                _note_direct(imp, imp_path)
                if imp_path in checked_modules:
                    _, source_ns = checked_modules[imp_path]
                    # design 229: the whole-module form binds no bare name, so
                    # its QUALIFIER is what `public import` re-exports — an
                    # importer of this module then reaches the dependency's
                    # surface through the chain.
                    whole_alias = (imp.alias or (imp.path[-1] if imp.path else ""))
                    _note_import(imp, whole_alias, '.'.join(imp_path),
                                 as_module=True)
                    self._bind_module_qualifier(
                        ns, imp, alias=whole_alias,
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

        # Design 254: the import list is complete, so publish this module's
        # `public import` edges and close its direct-import set over the graph.
        # ONE call, ahead of every body check below (and of the per-module save
        # at the end, so a generic instantiation re-checked in this module's
        # scope sees the same set its own file did). Dependencies are checked
        # first, so their edges are already on the table.
        self._public_imports_by_module[module_path] = set(public_edges)
        self._close_over_public_imports(direct_imports)

        # Register this module's own declarations

        # Save old state
        old_namespace = self.namespace
        old_module_path = self.current_module_path
        old_direct_imports = self.current_direct_imports
        old_module_source = self.current_module_source
        self.namespace = ns
        self.current_module_path = module_path
        self.current_direct_imports = direct_imports
        # DF-243b: what a module-level diagnostic names when no function or
        # method is in scope. Saved and restored beside the path it travels with.
        self.current_module_source = getattr(module_ast, 'source_path', None)

        # Validate: exports are only allowed in init.saw files (same rule as the
        # single-file path; enforced here so the unified pipeline still catches
        # a stray `export` in a regular entry/module file).
        self._validate_exports(module_ast)

        # design 148: const VALUE parameters, before any type-param list is read.
        self._resolve_const_params_in_program(module_ast)

        # DF-172j: this module's const-foldable statics, before the struct pass
        # resolves a field whose length names one.
        self._collect_const_statics(module_ast)
        # DF-232g residue: which file each declared length was written in, for
        # the codegen-raised refusal that has no enclosing declaration to ask.
        self._stamp_declared_type_sources(module_ast, self.current_module_source)
        self._fold_const_lengths_in_program(module_ast)

        # THE NAMES THIS MODULE DECLARES ITSELF, collected before any of them is
        # registered. The design-194 annotation gate asks whether the AUTHOR
        # could write a name bare, and the answer for a type the module itself
        # declares is yes wherever it sits — Saw has no forward declarations.
        # Accessibility is granted per declaration as the passes below walk
        # them, which made the gate declaration-ORDER sensitive: a field naming
        # a type declared further down the file was judged while that spelling
        # still meant only the gated std symbol, so `struct Holder { e: IoError
        # }` above `struct IoError` was refused with a hint to import
        # `std.net`. This set is the order-independent answer, and it is
        # deliberately NOT `directly_accessible` — that set is what
        # `_shadows_hidden_std` reads to tell an import from a redefinition.
        self._module_own_type_names = {
            d.name
            for group in (module_ast.type_definitions, module_ast.structs,
                          module_ast.enums, module_ast.traits)
            for d in group
        }
        # design 241 unit 1: the same question, one answer wider — the
        # undefined-type rule counts a trait's associated types too.
        self._collect_unit_type_names(module_ast)

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

        # DF-194b: entry point 2 of 2 — a module's own aliases are registered by
        # its own pass, not the entry's, so the rule is owed here too.
        self._reject_enum_underlying_aliases(module_ast)

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
        # "A public API needs public types" (user ruling, Aug 21) — see
        # `check`'s call for why it sits at this seam.
        self._check_signature_visibility_in_program(module_ast)
        # design 188 unit 1: the no-escape walk again, with aliases resolved.
        self._validate_no_ref_laundering_in_program(module_ast)

        # design 246 Unit A: entry point 2 of 2 — a module's own declarations
        # are registered by its own pass, so the rule is owed here too.
        self._check_recursive_type_sizes(module_ast)

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
                    self.current_module_source = old_module_source
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
        self._check_main_return_type(module_ast)

        # Enable import checking for this module
        ns.enable_import_checking()

        self._capture_pristine_templates(module_ast)

        # Type check function bodies
        for func in module_ast.functions:
            if getattr(func, 'is_mono_instance', False):
                # A synthesized instantiation spliced in by the effect pass
                # (design 70). Only the place lowering's re-entry gets this far
                # — a first pass builds the clone after this loop — and it must
                # reach the same verdict the first pass did.
                #
                # design 218 unit 1.5 stage 2 (§1c, T11): this used to check
                # the clone and then DELETE the diagnostics, on the grounds
                # that they were not the author's. That rationale is RETIRED:
                # the errors an instance raises are real now, and the reason
                # they were not the author's — every type here arrived by
                # substitution — is stated as NAMED PER-RULE SKIPS instead, so
                # design 132's "a Void you can SEE" stands down while the
                # ownership rules do not. What survives is the SCHEDULING role
                # the entry always had: an instance is checked as an instance,
                # with its attribution and its skips, wherever it is checked.
                with self._checking_instance(func.name):
                    self._check_function(func)
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
            # DF-289a: FIRST claim wins, and modules are checked in dependency
            # order with the entry LAST — see `_module_source_files`.
            self._module_scope_by_file.setdefault(_src, (module_path, ns))
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
        self.current_module_source = old_module_source

        # Whole-program `sync` effect analysis (design 22). The entry module is
        # checked last, after every other module's bodies have contributed their
        # call-graph edges, so this runs once over the complete graph.
        if is_entry:
            self.finalize_effects()
            # design 219 wave C: same reason, same place — every module's
            # bodies have been walked, so every callee's requirement is known.
            self._tier_discharge_all()

        if self.reporter.has_errors():
            return None

        return ns

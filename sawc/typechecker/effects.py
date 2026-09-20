"""
design 22 — `sync` effect system prototype (the flip, investigated early).

Whole-program transitive suspendability inference plus `sync`-context checking.

Model (design 18 Axis B'): calls are COLORLESS — any call may suspend. The
marker sits on the rare side: `sync` is a checked negative effect. A
function / method / closure "suspends" iff its body transitively reaches a
suspension source:

  * the `__saw_test_suspend()` intrinsic (synthetic suspension point),
  * a call to an `extern blocking func` (unbounded FFI),
  * a call to a suspending function/method (transitive), or
  * a call THROUGH a non-`sync` function-typed value (conservative — this is
    where effect polymorphism bites; see designs/22-findings.md).

A `sync` context — a `sync func`, a `deinit` body, or a value whose target
type is a `sync (...)` function type (e.g. `Mutex.lock`'s closure parameter) —
must be transitively suspension-free. A violation is reported with the full
suspension PATH: `... closure calls f -> g -> __saw_test_suspend (g suspends at
line N)`.

Implementation strategy: the call graph is collected DURING type checking
(reusing the checker's name/type resolution), keyed by AST identity, into
instance state on the TypeChecker. After all bodies are checked, a single
iterate-to-fixpoint pass computes each node's `suspends` bit (SCC-correct for
mutual recursion), then every sync context is checked and diagnosed.

Scope guard: no executor, no state machines, no async/await. `__saw_test_suspend`
codegens to a no-op; this pass is pure typechecker machinery.
"""

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from errors import ErrorKind
from mono_copy import substitute_constructed_type_param, substituting_copy
from monomorphize import substituted_param_names


def _first_pristine(entries):
    """The first (Method, Extension) of a pristine-store bucket, or None.

    DF-289c made every bucket a LIST — the (struct, method NAME) key is not
    unique. The design-70/74 builders ask by NAME and have always used whatever
    that name answered with, so "first" is what keeps their behaviour identical;
    a reader that must tell same-named siblings apart calls
    `TypeChecker.pristine_method_for` instead.
    """
    return entries[0] if entries else None


def substitute_ast_types(node, type_map):
    """In-place: rewrite every `SawType` in an AST subtree through
    `SawType.substitute(type_map)` (design 70). `SawType.substitute` recurses
    through nested type structure, so this walker only has to reach each
    SawType-valued field once. Walks any dataclass node (AST nodes,
    `Parameter`, `Argument`, `StructField`, …) but treats a `SawType` itself as
    a leaf (handled by `_subst_ast_value`).

    ENTRY POINT — exactly one, since design 218c Amendment A2(a) took the four
    CLONE paths away: building an instance is `mono_copy.substituting_copy`,
    which copies and substitutes in ONE pass instead of deep-copying a whole
    template and then rewriting the copy. What is left is the caller that
    substitutes a subtree it ALREADY owns — `_build_generic_struct_method_mono`'s
    post-check re-stamp, which runs over the checked clone because
    `_resolve_type` leaves a `self`-field read abstract and the frame layout
    needs the concrete type. A caller that wants a CLONE must not reach here:
    two walks over one subtree is what A2(a) removed.
    """
    from ast_nodes import SawType, FunctionCall
    if not dataclasses.is_dataclass(node) or isinstance(node, (SawType, type)):
        return
    # DF-285a: a type parameter is not always spelled as a TYPE. `A()` — design
    # 37's zero-sized allocator construction — spells one in CALL-NAME position,
    # and a call's name is a `str`, so the loop below cannot reach it however
    # completely it walks. ONE definition of that rewrite, in `mono_copy`, where
    # the copier applies it as it builds the node.
    if isinstance(node, FunctionCall):
        substitute_constructed_type_param(node, type_map)
    # NOTE (design 126 R1): this deliberately walks `dataclasses.fields()`, not
    # `structural_fields()`. The typechecker's annotations carry SawTypes too, and
    # monomorphization must substitute those as well -- while they were runtime
    # grafts this walker could not see them at all.
    for f in dataclasses.fields(node):
        setattr(node, f.name, _subst_ast_value(getattr(node, f.name), type_map))


def _subst_ast_value(val, type_map):
    from ast_nodes import SawType
    if isinstance(val, SawType):
        return val.substitute(type_map)
    if dataclasses.is_dataclass(val) and not isinstance(val, type):
        substitute_ast_types(val, type_map)
        return val
    if isinstance(val, list):
        return [_subst_ast_value(v, type_map) for v in val]
    if isinstance(val, tuple):
        return tuple(_subst_ast_value(v, type_map) for v in val)
    return val


def _instance_display(base, method_name, type_args, method_type_args):
    """One instance in SOURCE spelling, for design 218c §3's attribution note.

    `launder<Res>`, `Holder<Int>.mix<Bool>` — the reader's name for it, never
    the mangled symbol, which is the identity and is unreadable at any depth.
    """
    def spell(args):
        return "<" + ", ".join(str(a) for a in args) + ">" if args else ""

    name = f"{base}{spell(type_args)}"
    if method_name:
        name = f"{name}.{method_name}{spell(method_type_args)}"
    # design 144's internal module qualifier is scrubbed by the reporter, but
    # this string is also read by tests and traces, so keep it short here too.
    return name.replace("$m$", "@")


@dataclass
class SuspendSource:
    """A place where a node suspends without going through another node."""
    label: str   # e.g. "__saw_test_suspend", "blocking extern `read`"
    line: int


# The REAL cooperative primitives (design 45 item 1, design 76). A source
# labelled with one of these means the body actually hands control back to the
# executor (or blocks on it); every OTHER source in the graph is the
# conservative "a call through a non-`sync` function value" one, which any
# closure-taking call raises and which must NOT, on its own, wrap `main` in an
# entry executor or pull a body into the coroutine transform's driven closure.
REAL_SUSPEND_LABELS = ("yield_now", "sleep", "__saw_io_park", "io_wait",
                       "io_wait_until", "__saw_chan_park")


_BLOCKING_SOURCE_PREFIX = "blocking extern"

# THE conservative source, spelled once. `_effect_indirect_call` is the only
# place that produces it: a call through a non-`sync` function VALUE might
# suspend, because the value's own effect is not in the type. Every consumer that
# needs "does this body suspend for a reason of its OWN" strikes out exactly this
# label — see `frame_boundary`.
CLOSURE_CALL_SOURCE_LABEL = "a call through a non-`sync` function value"

# The two synthetic suspension points (`typechecker/expressions.py`, one site):
# design 22's effect-only `__saw_test_suspend` and design 44's state boundary
# `__saw_suspend`, which lower to the same no-op outside a driven closure. Both
# are FRAME boundaries and neither needs an executor.
_FRAME_INTRINSIC_LABELS = ("__saw_suspend", "__saw_test_suspend")

# design 223 unit 3's source: ``a call through `any Trait` dispatch``, one per
# trait, so it is matched by prefix. `CLOSURE_CALL_SOURCE_LABEL` is tested for
# equality before this, and the two spellings differ from the fourth word on.
_EXISTENTIAL_SOURCE_PREFIX = "a call through `any "

# What `_effect_path` answers when it can reach no source at all — a shape that
# should not exist for a suspending node. Named so a caller BUILDING a table can
# test for it instead of letting it reach a user-facing message.
PATH_PLACEHOLDER_LABEL = "<suspension source>"


# design 275 U4 — THE CAUSES. Every suspension source in the graph is one of
# these, and the analysis answers ONE question per node: WHICH causes can reach
# it. Every predicate anybody asks — "must this `sync` body be refused?", "does
# `main` need an executor?", "must this body be framed?" — is a DERIVED READ of
# that set (the five named derivations below), so no consumer re-derives a
# subset privately. A three-valued answer would have forced exactly that
# re-derivation: the four predicates this unit replaces exist BECAUSE each
# consumer needs a different subset of the causes.
class SuspendCause:
    """One bit per KIND of suspension source.

    TOTAL over the labels `_effect_direct_source` produces (`_source_class` maps
    each one); an unrecognized label falls to `UNCLASSIFIED`, whose membership in
    the derivations below is the conservative one a new source had before this
    existed.
    """
    # A real cooperative primitive: `yield_now`, `sleep`, `io_wait`,
    # `io_wait_until`, `__saw_io_park`, `__saw_chan_park` (REAL_SUSPEND_LABELS),
    # or a seeded std leaf that reaches one. The body hands control back to the
    # executor, so there has to BE one.
    COOPERATIVE = 1
    # A `blocking` extern call — design 103's thread offload. It needs the
    # executor too, and design 242 ruling 9 PERMITS it in a `Thread.spawn` body,
    # which is the one derivation that tells the two apart.
    BLOCKING = 2
    # The test-only `__saw_suspend` / `__saw_test_suspend` intrinsic: a frame
    # boundary the transform must split at (design 44) that codegens to nothing,
    # so it must never wrap `main` in an executor. This ONE cause is the whole
    # difference between design 206's predicate and SL-306's, and mistaking it
    # for the others is the trap SL-306's agent hit.
    TEST_SUSPEND = 4
    # A call through `any Trait` dispatch (design 223 unit 3). Conservative — a
    # vtable word carries no effect — and `_report_existential_suspend_dispatch`
    # refuses at the DISPATCH when some conformance really suspends. Its OWN
    # cause because the two predicates it sat between disagreed about it and
    # always had: design 206's struck it, SL-306's did not. See the note on
    # `frame_boundary`.
    EXISTENTIAL_DISPATCH = 8
    # THE conservative closure-call source (`CLOSURE_CALL_SOURCE_LABEL`): a call
    # through a non-`sync` function VALUE, which every closure-taking body raises
    # and which says only "might".
    CLOSURE_CALL = 16
    # Any source label this classifier does not know. Never produced today.
    UNCLASSIFIED = 32

    ALL = (COOPERATIVE | BLOCKING | TEST_SUSPEND | EXISTENTIAL_DISPATCH
           | CLOSURE_CALL | UNCLASSIFIED)
    # (bit, name) for reporting — the equivalence probe and any future dump.
    NAMES = (
        (COOPERATIVE, "cooperative"),
        (BLOCKING, "blocking"),
        (TEST_SUSPEND, "test_suspend"),
        (EXISTENTIAL_DISPATCH, "existential_dispatch"),
        (CLOSURE_CALL, "closure_call"),
        (UNCLASSIFIED, "unclassified"),
    )


def describe_causes(causes: int) -> str:
    """`{cooperative, closure_call}` — the cause set, spelled, for a report."""
    named = [name for bit, name in SuspendCause.NAMES if causes & bit]
    return "{" + ", ".join(named) + "}"


# --------------------------------------------------------------------------
# THE NAMED DERIVATIONS (design 275 U4). ONE row per context decision, each
# naming its consumers; a consumer that needs a subset no row names ADDS A ROW
# here rather than combining bits at its own site. These five, and the fact that
# they are the only readers of a cause set, are what keep the four walkers this
# unit deleted from growing back.
# --------------------------------------------------------------------------

def might_suspend(causes: int) -> bool:
    """ANY cause — "this body is not provably suspension-free".

    THE REFUSING question: a `sync` body that maps a vector with an unknown
    closure might suspend and is refused on exactly this.

    CONSUMERS: `EffectsMixin.finalize_effects`' sync-context check and
    `SuspendNode.suspends` (the field every node-holding reader consults);
    `consumes._check_consumes_suspending_fences` (design 260's two fences);
    `coro_ledger.FrameLedger.might_suspend_free` (which is what
    `coro_transform._find_suspending_cycle` and `_default_expr_suspends` ask) and
    `_build_frame_ledger`'s BROAD method census + its `_answered_locally`
    override; `sawc.build_builtin_namespace`'s
    `_std_suspending_methods` and `_std_suspending_functions` (the latter read by
    `docs_emit` for `--emit-docs`).
    """
    return bool(causes)


def wraps_main(causes: int) -> bool:
    """`cooperative | blocking` — "a live EXECUTOR has to exist for this".

    Design 45 item 1's entry gate, which is what the row is named for: a
    suspending `main` is wrapped in the entry executor. `test_suspend` is
    deliberately OUT (it codegens to nothing and is reached only through an
    explicit `__saw_drive`), and so are the two conservative causes, which say
    only that a body might.

    CONSUMERS: `finalize_effects`' `_main_suspends`;
    `sawc.build_builtin_namespace`'s `_std_really_suspending_methods`, the table
    `_effect_seed_std_methods` mints leaf nodes from (a merely-conservative std
    method must not become a leaf, or every `deinit` that maps a vector would be
    a suspension error); and `_report_existential_suspend_dispatch`, design 223
    unit 3's refusal, which fires only for a conformance body that really parks.
    """
    return bool(causes & (SuspendCause.COOPERATIVE | SuspendCause.BLOCKING))


def refused_in_thread_body(causes: int) -> bool:
    """Every cause but `blocking` — design 242 ruling 9's question.

    A `Thread.spawn { ... }` body may block its own thread on FFI (that is the
    point of spawning one) and must still be refused every OTHER way of
    suspending, because no executor runs on that thread to resume it.
    Blocking-ness is a property of the SOURCE, so a helper the body calls is
    struck on the same terms — which is what makes `Thread.spawn { drain(fd) }`
    legal for a `drain` written around a blocking extern.

    CONSUMERS: `finalize_effects`' `blocking_permitted` narrowing, and nothing
    else — a thread body is the one context that permits one cause and refuses
    the rest.
    """
    return bool(causes & ~SuspendCause.BLOCKING & SuspendCause.ALL)


def frame_boundary(causes: int) -> bool:
    """Every cause but `closure_call` — "this body owns a suspension a FRAME has
    to be built around".

    `cooperative | blocking | test_suspend` are the boundaries design 44 splits a
    state machine at. `closure_call` is read for NOTHING here, which is SL-306's
    rule stated positively: a body that "suspends" only because it calls a
    non-`sync` function value has no park to host, and framing it put the
    closure-body rejector in front of programs with no suspension in them.

    THE ONE MEMBERSHIP THAT IS RECORDED RATHER THAN RULED: `existential_dispatch`
    counts here, because SL-306's predicate counted it and this unit is
    behaviour-preserving. It is a conservative cause — a vtable word carries no
    effect, and design 223 refuses the dispatch outright when a conformance body
    really suspends — so a body whose ONLY cause is one is framed today although
    it owns no park. Probed, filed, and left alone: moving it into
    `closure_call`'s half is a behaviour flip that belongs to the ledger unit.

    CONSUMERS: `finalize_effects`' `closure_calls_permitted` narrowing (a
    SYNTHESIZED frame method's `sync` marker guards exactly this invariant);
    `coro_transform._build_frame_ledger`'s OWN method census (read back as
    `FrameLedger.method_owns_suspension`), its closure-walk edge-follow
    (`FrameLedger.edge_is_boundary`) and `FrameLedger.free_boundary`;
    `FrameLedger.instantiation_is_boundary`, which both generic promotions ask; and
    `sawc.build_builtin_namespace`'s `_std_suspending_methods_ignoring_closure_calls`.
    """
    return bool(causes & ~SuspendCause.CLOSURE_CALL & SuspendCause.ALL)


def closure_only(causes: int) -> bool:
    """`closure_call` and nothing else — the conservative answer, alone.

    CONSUMERS: none in the compiler today, deliberately. It is the diagnostics
    row: the answer to "why is this body not framed although it might
    suspend?", and the shape a future reader should reach for instead of
    spelling `might_suspend(c) and not frame_boundary(c)` at a site of its own.
    """
    return causes == SuspendCause.CLOSURE_CALL


def _source_class(source: SuspendSource) -> int:
    """The ONE mapping from a SOURCE to its `SuspendCause`."""
    return cause_of_label(source.label)


def cause_of_label(label: str) -> int:
    """The ONE mapping from a source LABEL to its `SuspendCause`.

    Public because `sawc.build_builtin_namespace` asks it of a label it is about
    to hand to the std seed — the seeded leaf must carry a source for the cause
    a diagnostic may strike, and "is this label the blocking one?" is this
    question, not a second prefix test beside it.
    """
    if label in REAL_SUSPEND_LABELS:
        return SuspendCause.COOPERATIVE
    if label.startswith(_BLOCKING_SOURCE_PREFIX):
        return SuspendCause.BLOCKING
    if label == CLOSURE_CALL_SOURCE_LABEL:
        return SuspendCause.CLOSURE_CALL
    if label.startswith(_EXISTENTIAL_SOURCE_PREFIX):
        return SuspendCause.EXISTENTIAL_DISPATCH
    if label in _FRAME_INTRINSIC_LABELS:
        return SuspendCause.TEST_SUSPEND
    return SuspendCause.UNCLASSIFIED


class SuspensionAnswers:
    """The CAUSE SET of every node in one effect graph, and the five derived
    reads of it (design 275 U4).

    Built by `classify_suspensions`. Nothing outside this file derives a
    suspension answer from `SuspendSource` labels, walks the edges to find one,
    or combines cause bits of its own — a consumer asks one of the five named
    derivations, and a consumer that needs a subset none of them names adds a
    row up there.
    """

    __slots__ = ("_causes",)

    def __init__(self, causes: Dict[Any, int]):
        # key -> the union of every `SuspendCause` bit reachable from that node.
        self._causes = causes

    def causes(self, key) -> int:
        """The cause SET reachable from `key` (0 for an unknown key)."""
        return self._causes.get(key, 0)

    def might_suspend(self, key) -> bool:
        return might_suspend(self._causes.get(key, 0))

    def wraps_main(self, key) -> bool:
        return wraps_main(self._causes.get(key, 0))

    def refused_in_thread_body(self, key) -> bool:
        return refused_in_thread_body(self._causes.get(key, 0))

    def frame_boundary(self, key) -> bool:
        return frame_boundary(self._causes.get(key, 0))

    def closure_only(self, key) -> bool:
        return closure_only(self._causes.get(key, 0))


def classify_suspensions(nodes) -> SuspensionAnswers:
    """THE suspension analysis, run ONCE per graph (design 275 U4).

    One monotone, SCC-safe propagation: a node's cause set is the union of its
    own direct sources' causes and every cause its callees reach. `suspends`,
    design 206's executor gate, design 242 ruling 9's thread narrowing and
    SL-306's framing question were four separate walks of this same graph, each
    computing one BIT of what this computes in one pass; they are the derivations
    above now, so they cannot drift apart and no consumer can quietly grow a
    fifth.

    ENTRY POINTS (obligation 1 — every caller, with the derivation it reads):

      * `EffectsMixin.finalize_effects` — stamps `SuspendNode.causes` on every
        node (so a reader holding a NODE asks the same set, never a second
        analysis), then reads `wraps_main` for `_main_suspends`,
        `refused_in_thread_body` for a design-242 thread body, `frame_boundary`
        for a SYNTHESIZED frame method's `sync` marker, and hands the table to
        `_report_existential_suspend_dispatch` (`wraps_main`). The sync-context
        check and `_check_consumes_suspending_fences` read `might_suspend`
        through `SuspendNode.suspends`.
      * `sawc.build_builtin_namespace` — the three std censuses over the BUILTIN
        graph, which the entry compile cannot compute because it never checks a
        std body: `_std_suspending_methods` (`might_suspend`, name pairs),
        `_std_really_suspending_methods` (`wraps_main`, keyed by node id — the
        table `_effect_seed_std_methods` mints leaf nodes from, carrying the
        CAUSE SET so a seeded leaf answers every derivation the way the std body
        it stands for does) and
        `_std_suspending_methods_ignoring_closure_calls` (`frame_boundary`, name
        pairs), plus `_std_suspending_functions` (`might_suspend`) for
        `--emit-docs`.
      * `coro_transform._build_frame_ledger` — ONE table for the whole transform,
        held by the design-275-U1 discovery LEDGER, which is the only thing that
        reads it: the `(struct, method)` censuses (`might_suspend` broad,
        `frame_boundary` own), which `FrameLedger.method_target` reads in that
        order (broad gate, then the framing question); the closure walk's
        edge-follow and `free_boundary` (`frame_boundary`);
        `instantiation_is_boundary`, which both generic promotions ask
        (`frame_boundary`); and `might_suspend_free`, which the cycle check and
        the suspending-parameter-default refusal ask.
    """
    causes: Dict[Any, int] = {}
    for key, node in nodes.items():
        mask = node.seeded_causes
        for s in node.direct:
            mask |= _source_class(s)
        causes[key] = mask
    changed = True
    while changed:
        changed = False
        for key, node in nodes.items():
            mask = causes[key]
            grown = mask
            for e in node.edges:
                grown |= causes.get(e.target, 0)
            if grown != mask:
                causes[key] = grown
                changed = True
    return SuspensionAnswers(causes)


@dataclass
class SuspendEdge:
    """A call from one node to another (potentially suspending) node."""
    target: Any  # key of the callee node
    short: str   # short display of the callee for path chains (e.g. "`g`")
    line: int


@dataclass
class SuspendNode:
    """One analyzable body: a function, a method, or a closure."""
    key: Any
    short: str                          # used in path chains ("`f`", "closure")
    desc: str                           # human descriptor for a violation
    line: int
    column: int
    source_file: Optional[str]
    sync_reason: Optional[str] = None   # non-None => this is a `sync` context
    # The hint a violation of THIS context prints. None takes the general
    # "hoist it out of the sync region" advice; a context whose sync-ness comes
    # from a rule the author did not write (design 219's copy-policy `copy()`)
    # supplies its own, because the general advice cannot name that rule.
    sync_hint: Optional[str] = None
    # design 242 ruling 9: this sync context PERMITS a `blocking` extern. Set on
    # a `Thread.spawn { ... }` body and nowhere else — the thread is the
    # author's to block, which is the headline reason to reach for one. Every
    # OTHER suspension source is refused there exactly as in any sync context,
    # so the flag narrows one rule rather than opening a hole.
    blocking_permitted: bool = False
    # SL-306 review r2: this sync context is a SYNTHESIZED frame method — a
    # `sync` declaration the compiler wrote, not the author — so the conservative
    # closure-call source does not violate it. Set on a `is_sync` +
    # `is_synthesized` method and nowhere else. Narrows ONE rule, exactly as
    # `blocking_permitted` does, and for the same kind of reason: what a frame
    # method's `sync` marker protects is the invariant that the transform left no
    # REAL suspension un-lowered in a resume body, and a callee that only "might"
    # suspend because it calls a non-`sync` function value is a plain call the
    # frame is right to make. Every other source is refused there as ever —
    # including the test-only `__saw_suspend`, which is a state boundary a resume
    # must never still contain.
    closure_calls_permitted: bool = False
    direct: List[SuspendSource] = field(default_factory=list)
    edges: List[SuspendEdge] = field(default_factory=list)
    # design 275 U4: THE cause set (`SuspendCause` bits) reaching this node,
    # stamped by `finalize_effects` out of the one `classify_suspensions` pass.
    # 0 until the graph has settled — which is also what it means for a node
    # minted after the last settling.
    causes: int = 0
    # Causes this node carries that no `direct` source spells. Exactly one
    # producer: `_effect_seed_std_methods`, which mints a LEAF for a std method
    # whose body belongs to another typechecker's graph, carrying the cause set
    # the builtin compile computed for it. Kept apart from `direct` because
    # `direct` is also the diagnostic PATH's material (`_effect_path` names one
    # representative source), and a seeded leaf needs one label and a whole set.
    seeded_causes: int = 0
    # design 70 (A5) had a `poly_candidate` flag here — set when a body called a
    # method on a type-PARAMETER receiver, and read in exactly one place, to
    # decide whether a deferred template-named call edge was worth materializing
    # into an instance one. Design 266 U3 deleted that decision: every demanded
    # instance is materialized and instance-checked by phase 2 and the edge is
    # recorded against it at monomorphization time, so there is no deferral left
    # to gate. Per-instantiation effect re-inference is unchanged — it is what
    # the instance check has always been.

    @property
    def suspends(self) -> bool:
        """`might_suspend` read off this node's own cause set.

        DERIVED, never assigned, so the broad bit and the cause set cannot
        disagree the way the separate fixpoints that computed them could
        (design 275 U4). The readers that hold a node and want this question are
        `_effect_path`, `_check_consumes_suspending_fences`,
        `coro_transform._find_suspending_cycle`, `_default_expr_suspends` and
        the `(struct, method)` census in `transform_program`; a reader that wants
        another derivation asks `SuspensionAnswers` for it by name.
        """
        return might_suspend(self.causes)


class EffectsMixin:
    """Mixed into TypeChecker; owns the design-22 suspend analysis."""

    # ------------------------------------------------------------------ setup
    def _effect_init(self):
        # Keyed by ("fn", name) for free functions, `Method.node_id` for methods,
        # and `ClosureExpr.node_id` for closures (design 126 R2 -- these were
        # `id()`, i.e. addresses). The two shapes stay distinguishable: a
        # free-function key is a tuple, a method/closure key a plain int.
        self._suspend_nodes: Dict[Any, SuspendNode] = {}
        self._suspend_stack: List[SuspendNode] = []
        # design 275 U4: the last settling's `SuspensionAnswers` — the ONE walk
        # `finalize_effects` computes, kept so a reader that has the typechecker
        # but not a node can ask the same table rather than walk again. Empty
        # until the first settling.
        self._suspension_answers = SuspensionAnswers({})
        # design 206: the std METHODS that REALLY suspend, as
        # `Method.node_id -> (short, real-source label, line)`. Empty here and
        # filled by the driver out of the builtin namespace (`sawc.py`), because
        # only the builtin typechecker ever analyzes a std body. Empty is the
        # right default for the BUILTIN compile itself, which has those bodies in
        # front of it. `_effect_seed_std_methods` mints a leaf node per entry.
        self._std_really_suspending_methods: Dict[Any, tuple] = {}
        # SL-306: the std methods that suspend for a reason of their OWN — every
        # source but the conservative closure-call one — as `(struct, method)`
        # NAME PAIRS, filled from the builtin namespace by the same driver. The
        # coroutine transform's call-site classifier asks by name, because a std
        # method has no node in this graph for the node-id table above to answer
        # for; without this it could not tell `TcpStream.read` (a real park) from
        # `JsonValue._write` (a recursion inside a `Vector.each` closure).
        self._std_suspending_methods_ignoring_closure_calls: Set[tuple] = set()
        # design 44: free-function names driven by a `__saw_drive(...)` /
        # `__saw_drive_steps(...)` site, mapped to the set of driver modes requested
        # ({"value", "steps"}). A driven root and its suspending callees are the
        # closure the coroutine transform rewrites into frames + resume methods.
        self._driven_roots: Dict[str, set] = {}
        # design 45 Part 0c: driven suspending METHODS, keyed by
        # (struct_name, method_name) -> set of driver modes. The receiver lives in
        # the frame as a pointer into the task root (D6 task confinement).
        self._driven_method_roots: Dict[tuple, set] = {}
        # design 52b item 2: free functions SPAWNED into a TaskGroup
        # (`group.spawn(f(args))`), name -> f's return SawType. A spawn root gets a
        # frame + `Resumable` conformance like a driven root, plus a synthesized
        # `__spawn_<f>` helper (boxes the frame, enqueues it, returns
        # `Task<T>`) — but no `__saw_drive_*` driver.
        self._spawn_roots: Dict[str, Any] = {}
        # design 75 (A2): spawn roots spawned into a MULTI-THREADED group
        # (`TaskGroup(threads: N)`). Their frames cross OS-thread boundaries, so the
        # coroutine transform gates every across-suspend live value on `Send`.
        self._mt_spawn_roots: set = set()
        # design 242 ruling 3: spawn roots spawned into the BACKGROUND singleton
        # (`Task.spawn(f(args))`). A root here gets a second helper beside
        # `__spawn_<f>` — `__bgspawn_<f>`, which takes no group parameter and
        # reads the process-wide group instead — and its presence is what makes
        # the transform wrap `main` with the group's close.
        self._background_spawn_roots: set = set()
        # design 70 (A5): effect polymorphism via monomorphization-time
        # re-inference. Pristine (pre-body-check) copies of every generic function
        # template, keyed by name, so an instantiation can be cloned + substituted
        # + re-checked to get its OWN effect node keyed by the mangled symbol.
        self._pristine_generics: Dict[str, Any] = {}
        # Amendment A1 (DF-285b): the same three stores for STD's templates,
        # captured by the SEPARATE typechecker inside `build_builtin_namespace`
        # and handed over with its cached namespace. Kept apart from the three
        # above because they belong to two different compiles — see the union
        # lookups `pristine_generic` / `pristine_generic_method` /
        # `pristine_generic_struct_method` in `core.py`, which are how anything
        # reads the store as one.
        self._std_pristine_generics: Dict[str, Any] = {}
        self._std_pristine_generic_methods: Dict[Any, Any] = {}
        self._std_pristine_generic_struct_methods: Dict[Any, Any] = {}
        # Queued instantiation builds: list of (template_name, resolved_type_args,
        # mangled). Driven / spawned / method-generic roots queue eagerly (the
        # mangled name is needed at the site to rewrite the call); the build (clone
        # + re-check) is deferred to `_process_effect_monos`.
        self._pending_mono: List[Any] = []
        self._mono_built: set = set()   # mangled symbols already built/queued
        # Method-generic instantiations (design 70): pristine templates keyed by
        # (struct_name, method_name) -> (Method, owning Extension), and queued
        # concrete builds (struct_name, method_name, resolved_args, mono_name).
        # (struct_name, method_name) -> LIST of (Method, owning Extension)
        # (DF-289c: the name is not a unique key).
        self._pristine_generic_methods: Dict[Any, Any] = {}
        self._pending_method_mono: List[Any] = []
        # design 74 (A5-rest, shape 2): pristine methods on GENERIC-struct
        # extensions, keyed by (struct_name, method_name) -> (Method, Extension).
        # A driven `__saw_drive(b.run())` with `b: Holder<Int>` monomorphizes the
        # method over the struct's type params and records the concrete driven
        # method here (keyed by a per-instantiation mono method name), carrying the
        # concrete receiver SawType (`Holder<Int>`) the frame's `__recv` needs.
        # A LIST per key, for DF-289c's reason.
        self._pristine_generic_struct_methods: Dict[Any, Any] = {}
        # (base_struct, mono_method_name) -> (recv_saw_type, mono_method_ast).
        self._driven_generic_struct_methods: Dict[Any, Any] = {}
        # Queued generic-struct-method builds: (struct_name, method_name,
        # resolved_struct_args, mono_name, recv_type). The clone+substitute+re-check
        # is deferred to `_process_effect_monos` (safe there — not nested inside
        # another body check, so it won't clobber the active scope).
        self._pending_generic_struct_method_mono: List[Any] = []
        # (Design 266 U3 deleted `_poly_call_edges` from here — census row T5's
        # deferred template-named call edges. The edge is recorded at
        # monomorphization time now, against the INSTANCE, and lives on the
        # registry until `monomorphize.apply_effect_edges` files it.)
        # design 223 unit 3 (DF-223b). A frame is a COMPILE-TIME identity — the
        # caller embeds the callee's frame by value — and dynamic dispatch has
        # none, so a suspending conformance body reached through `any Trait` can
        # neither be embedded nor driven. It was not refused either: the dispatch
        # is a merely-CONSERVATIVE suspension source (the executor question
        # excludes it, exactly as it excludes a call through a closure), so no
        # frame was built anywhere in the program and the `yield_now()` inside
        # the impl ran outside a frame, where it is a no-op.
        #
        # Deciding it needs the fixpoint, which has not run when a dispatch is
        # checked — so the two halves are recorded here and joined in
        # `finalize_effects`:
        #   * every existential dispatch SITE, for the anchor;
        #   * every (trait, method) a conformance implements, for the answer.
        self._existential_dispatch_sites: List[Any] = []
        self._trait_impl_nodes: Dict[Any, Any] = {}
        # `finalize_effects` is RE-ENTRANT (design 218c §1a phase 3, which runs
        # after phase 2's monomorphization) and its fixpoint is monotone, so a
        # later settling can only ADD suspending nodes. Its three diagnostics
        # are not monotone in that sense — each must fire exactly once — so the
        # funnel keeps one ledger of what it has already said. Tokens are
        # ("sync", node key), ("consumes-fence", method node id) and
        # ("existential", site tuple).
        self._effects_reported: Set[Any] = set()

    def _effect_record_driven(self, name: str, mode: str):
        self._driven_roots.setdefault(name, set()).add(mode)

    def _effect_record_spawn(self, name: str, return_type):
        self._spawn_roots[name] = return_type

    def _effect_record_background_spawn(self, name: str):
        self._background_spawn_roots.add(name)

    def _effect_record_driven_method(self, struct_name: str, method: str, mode: str,
                                     resolved_symbol=None):
        # design 95: key a driven method by its resolved-signature FRAME KEY, so two
        # overloads of the same method name driven directly each get their own frame
        # (a name-only key collapsed them). `resolved_symbol` is the design-55
        # overload-mangled symbol on the `__saw_drive`d MethodCall (None for a
        # non-overloaded method / a monomorphized generic clone → plain key). The
        # value carries the struct/method/symbol the coroutine transform needs plus
        # the accumulated drive modes.
        frame_key = resolved_symbol or f"{struct_name}_{method}"
        entry = self._driven_method_roots.get(frame_key)
        if entry is None:
            entry = {'struct': struct_name, 'method': method,
                     'symbol': resolved_symbol, 'modes': set()}
            self._driven_method_roots[frame_key] = entry
        entry['modes'].add(mode)

    def _effect_absorb_scope(self):
        """A context manager-ish pair: push a throwaway suspend node so effect
        edges recorded while checking a `__saw_drive` argument attach to it (and are
        discarded) rather than to the enclosing function — the driver ABSORBS the
        callee's suspension (like `block_on`), so `__saw_drive`'s caller does not
        become suspending. Returns the sentinel to pass back to `_effect_unabsorb`.
        """
        sentinel = SuspendNode(key=None, short="<driver>", desc="<driver>",
                               line=0, column=0, source_file=None)
        self._suspend_stack.append(sentinel)
        return sentinel

    def _effect_unabsorb(self, sentinel):
        # Pop until (and including) the sentinel, staying robust to nested pushes.
        while self._suspend_stack:
            top = self._suspend_stack.pop()
            if top is sentinel:
                break

    # ------------------------------------------------------- node entry / exit
    def _effect_enter_function(self, func):
        # Overloading (design 55): a member of a 2+ overload set carries a
        # distinct stamped codegen symbol; key its suspend node on that so each
        # overload has its OWN effect node (a sync and a non-sync overload of the
        # same name must not merge into one node).
        #
        # SL-280: through `callee_frame_key`, the ONE answer to "what key names
        # this callee's frame?". The coroutine transform's tables and call-site
        # classifiers ask it too, so a node here and an edge there and a body
        # over in `funcs_by_name` are all filed under one string.
        from frame_keys import callee_frame_key
        key = ("fn", callee_frame_key(func))
        node = self._suspend_nodes.get(key)
        if node is None:
            from ast_nodes import is_exported
            is_sync = getattr(func, "is_sync", False)
            # design 58: an `@export`ed function is a C-boundary root that cannot
            # suspend (there is no Saw caller to drive it, and a coroutine frame
            # cannot cross a C ABI), so it is a `sync` context just like `main`'s
            # family — checked transitively suspension-free via the same machinery.
            exported = is_exported(func)
            if is_sync:
                reason = "`sync func` declaration"
            elif exported:
                reason = "an `@export` function"
            else:
                reason = None
            node = SuspendNode(
                key=key,
                short=f"`{func.name}`",
                desc=(f"`sync func {func.name}`" if is_sync
                      else (f"`@export func {func.name}`" if exported
                            else f"function `{func.name}`")),
                line=func.line,
                column=func.column,
                source_file=getattr(func, "source_file", None),
                sync_reason=reason,
            )
            self._suspend_nodes[key] = node
        self._suspend_stack.append(node)
        return node

    def _effect_enter_method(self, struct_name, method):
        key = method.node_id
        node = self._suspend_nodes.get(key)
        if node is None:
            mname = getattr(method, "name", "?")
            is_deinit = (mname == "deinit")
            is_sync = getattr(method, "is_sync", False)
            # design 219 unit A1 (DF-217r): the copy-policy retain hook, stamped
            # at registration. This is the THIRD way a method becomes a `sync`
            # context, and the only one the author does not spell — hence its
            # own hint, which names the rule and where the calls come from.
            copy_hook = getattr(method, "copy_policy_hook", None)
            reason = None
            hint = None
            if is_deinit:
                reason = "`deinit` context"
            elif copy_hook:
                reason = f"the `{copy_hook}` `copy()` of `{struct_name}`"
                hint = (
                    "a copy-policy `copy()` runs at compiler-inserted call "
                    "sites and must be `sync` (design 219): the compiler calls "
                    "it at every silent transfer, where no source construct "
                    "names a call, so a suspension here would break the `sync` "
                    "guarantee of whatever function the transfer sits in. Keep "
                    "the body the retain shape — cheap, infallible, "
                    "suspension-free")
            elif is_sync:
                reason = "`sync func` method"
            node = SuspendNode(
                key=key,
                short=f"`{struct_name}.{mname}`",
                desc=(f"`deinit` of `{struct_name}`" if is_deinit
                      else f"method `{struct_name}.{mname}`"),
                line=method.line,
                column=method.column,
                source_file=getattr(method, "source_file", None),
                sync_reason=reason,
                sync_hint=hint,
                # SL-306 review r2: a SYNTHESIZED `sync` method is a frame
                # method (`__Frame_f.resume` and its siblings), and its `sync`
                # marker guards the transform's own invariant rather than a
                # promise the author made. See `closure_calls_permitted`.
                closure_calls_permitted=bool(
                    is_sync and getattr(method, "is_synthesized", False)),
            )
            self._suspend_nodes[key] = node
        self._suspend_stack.append(node)
        return node

    def _effect_enter_closure(self, closure, expected_type):
        key = closure.node_id
        sync_reason = None
        if expected_type is not None and getattr(expected_type, "func_is_sync", False):
            sync_reason = "a `sync` closure context"
        node = self._suspend_nodes.get(key)
        if node is None:
            node = SuspendNode(
                key=key,
                short="closure",
                desc="closure",
                line=closure.line,
                column=closure.column,
                source_file=self._get_current_source_file(),
                sync_reason=sync_reason,
            )
            self._suspend_nodes[key] = node
        elif sync_reason and not node.sync_reason:
            node.sync_reason = sync_reason
        self._suspend_stack.append(node)
        return node

    def _effect_mark_thread_spawn_body(self, closure):
        """design 242 rulings 8 + 9: a `Thread.spawn { ... }` body is a `sync`
        context in which a `blocking` extern is nonetheless legal.

        Both halves in one place, because they are one decision about one
        context. Ruling 8: a suspending body needs an executor and the fresh OS
        thread has none, so `yield_now()` there is a no-op — which is precisely
        what it silently was (design 242 unit 0's probe: the body compiled as
        ordinary sync code with no frame in the emitted IR). Ruling 9: the
        thread exists to be blocked, so an unbounded FFI call runs DIRECTLY
        rather than being offloaded to yet another thread; that too was already
        what codegen emitted, and this makes it a rule rather than an accident.

        Applied AFTER the closure body is checked, on the node
        `_effect_enter_closure` minted for it — the flags feed the fixpoint's
        diagnosis pass, not the graph, so the order does not matter.
        """
        node = self._suspend_nodes.get(closure.node_id)
        if node is None:
            return
        node.sync_reason = "a `Thread.spawn { ... }` body"
        node.blocking_permitted = True
        node.sync_hint = (
            "a spawned thread runs no executor, so there is nothing there to "
            "resume a suspension — it would simply not cede. For suspending "
            "work on a dedicated thread write `TaskGroup(threads: 1)`, which "
            "brings an executor with it; a `blocking` extern is the one thing "
            "this body MAY do, and it blocks the spawned thread on purpose"
        )

    def _effect_exit(self):
        if self._suspend_stack:
            self._suspend_stack.pop()

    def _effect_current(self) -> Optional[SuspendNode]:
        return self._suspend_stack[-1] if self._suspend_stack else None

    # ------------------------------------------------- edge / source recording
    def _effect_direct_source(self, label: str, line: int):
        node = self._effect_current()
        if node is not None:
            node.direct.append(SuspendSource(label=label, line=line))

    def _effect_add_edge(self, target_key, short: str, line: int):
        node = self._effect_current()
        if node is not None and target_key is not None:
            node.edges.append(SuspendEdge(target=target_key, short=short, line=line))

    def _effect_call_function(self, func_info, name: str, line: int):
        """Record a resolved free-function / module-function call."""
        if getattr(func_info, "is_blocking", False):
            self._effect_direct_source(f"blocking extern `{name}`", line)
        else:
            # Free functions are keyed by name. A non-blocking extern (or any
            # name with no analyzed body) has no node and is a non-suspending
            # leaf, which is exactly the "extern promises promptness" rule.
            # Overloading (design 55): edge to the RESOLVED overload's node,
            # which is keyed by its stamped symbol (matches _effect_enter_function).
            # SL-280: both ends go through `callee_frame_key`, so the edge and
            # the node cannot drift apart the way the edge and the transform's
            # `imported_free_fns` table did.
            from frame_keys import callee_frame_key
            key_name = callee_frame_key(func_info, name=name)
            self._effect_add_edge(("fn", key_name), f"`{name}`", line)

    def _effect_call_method(self, method_info, short: str, line: int):
        ast = getattr(method_info, "ast_node", None)
        if ast is not None:
            self._effect_add_edge(ast.node_id, short, line)

    def _effect_indirect_call(self, func_type, line: int):
        """A call through a function-typed value. Non-`sync` => conservatively
        suspends (design 22 known-hard case: effect polymorphism).

        THE one producer of `CLOSURE_CALL_SOURCE_LABEL`, which is what lets
        `frame_boundary` strike this cause and only this one."""
        if not getattr(func_type, "func_is_sync", False):
            self._effect_direct_source(CLOSURE_CALL_SOURCE_LABEL, line)

    # ---------------------------------------------- design 70: effect polymorphism
    def _effect_queue_fn_mono(self, template_name: str, resolved_args) -> str:
        """Queue a build of the concrete instantiation `template_name<args>` and
        return its mangled symbol. Idempotent per mangled symbol. Used at driven /
        spawned / effect-polymorphic call sites where the concrete symbol is needed
        immediately (to rewrite the call) but the clone re-check is deferred to
        `_process_effect_monos`."""
        from codegen.mangle import mangle_function
        mangled = mangle_function(template_name, resolved_args)
        if mangled not in self._mono_built:
            self._mono_built.add(mangled)
            self._pending_mono.append((template_name, list(resolved_args), mangled))
        return mangled

    def _effect_queue_method_mono(self, struct_name, method_name, resolved_args,
                                  mono_name) -> bool:
        """Queue a build of the concrete method instantiation
        `struct_name.method_name<args>` (a method-level generic). Returns False if
        no pristine template is known (e.g. the method lives on a generic struct /
        another module — not supported here). Idempotent per (struct, mono_name)."""
        if (struct_name, method_name) not in self._pristine_generic_methods:
            return False
        marker = ("method", struct_name, mono_name)
        if marker not in self._mono_built:
            self._mono_built.add(marker)
            self._pending_method_mono.append(
                (struct_name, method_name, list(resolved_args), mono_name))
        return True

    def _effect_queue_generic_struct_method_mono(
            self, struct_name, method_name, resolved_args, method_args, mono_name,
            recv_type):
        """design 74 (A5-rest, shape 2) + design 104 item 3: queue a build of a
        driven suspending method on a GENERIC struct, monomorphized over the
        struct's type params for a concrete receiver (`Holder<Int>`) AND — when the
        method is ALSO method-generic (`mix<U>`) — over the method's own type params
        (`method_args`). Returns False if no pristine template is known (e.g. the
        method lives in another module — not supported here). Records the concrete
        receiver SawType eagerly (the frame's `__recv` needs it); the clone+re-check
        is deferred to `_process_effect_monos`."""
        if (struct_name, method_name) not in self._pristine_generic_struct_methods:
            return False
        key = (struct_name, mono_name)
        if key not in self._driven_generic_struct_methods:
            # Clone filled in by the deferred build; recv_type known now.
            self._driven_generic_struct_methods[key] = (recv_type, None)
            self._pending_generic_struct_method_mono.append(
                (struct_name, method_name, list(resolved_args), list(method_args),
                 mono_name, recv_type))
        return True

    def _build_generic_struct_method_mono(self, struct_name, method_name,
                                          resolved_args, method_args, mono_name):
        """Clone + substitute (struct type params + any method type params) +
        re-check one generic-struct driven method (design 74 shape 2, design 104
        item 3). The concrete method is NOT spliced onto an extension (its `self` is
        `Holder<Int>`, which a plain non-generic extension can't express); it is
        stored for the coroutine transform, which builds the frame with
        `__recv: UnsafePointer<Holder<Int>>` from it. The re-check stamps the
        resolved (concrete) types the frame builder consumes. Errors suppressed
        (effect / annotation harvest only)."""
        key = (struct_name, mono_name)
        recv_type, existing = self._driven_generic_struct_methods.get(key, (None, None))
        if existing is not None:
            return False
        entry = _first_pristine(
            self._pristine_generic_struct_methods.get((struct_name, method_name)))
        if entry is None:
            return False
        pristine, ext = entry
        struct_tps = ext.type_params or []
        method_tps = getattr(pristine, 'type_params', None) or []
        # Combined substitution: the struct's type params (T->Int, for `self`'s
        # fields) plus the method's own type params (U->Bool, for its params/locals).
        type_map = {tp.name: arg for tp, arg in zip(struct_tps, resolved_args)}
        type_map.update({tp.name: arg for tp, arg in zip(method_tps, method_args)})
        self._add_associated_type_bindings(type_map, struct_tps, resolved_args)
        self._add_associated_type_bindings(type_map, method_tps, method_args)
        clone = substituting_copy(pristine, type_map)
        clone.name = mono_name
        clone.type_params = []
        clone.is_mono_instance = True
        # type_subst binds `self` to `Holder<Int>` so field access through `self`
        # resolves the struct's `T`-typed fields to their concrete types, and maps
        # the method's own type params to their concrete arguments. In the
        # template's HOME module scope (design 210 unit 4), so a method body that
        # names its own module's private helper still finds it.
        #
        # design 218 unit 1.5 stage 2: ERRORS ARE REAL. This check used to
        # delete its own diagnostics — it was a type-stamping device wearing a
        # checker's clothes — so a genuine soundness fault in an instantiation
        # was found by nothing at all. `_checking_instance` names which
        # instance a diagnostic belongs to (§3) and turns on the §1c
        # provenance skips.
        with self._checking_instance(
                _instance_display(struct_name, method_name,
                                  resolved_args, method_args),
                substituted_params=substituted_param_names(pristine, type_map)):
            with self._instance_check_scope(clone, type_map):
                self._check_method(struct_name, clone, type_map)
        # The re-check stamps `resolved_type` on the body's expressions, but member
        # access through `self` resolves the struct's `T`-typed fields to `T` (the
        # generic StructSymbol carries `T`, and `_resolve_type` doesn't apply the
        # method's type_subst to a bare type param). Substitute AGAIN over the
        # stamped types so a frame local like `let before = self.value` gets the
        # concrete field type (Int) the frame layout needs — not `T` (or `U`).
        substitute_ast_types(clone, type_map)
        self._driven_generic_struct_methods[key] = (recv_type, clone)
        return True

    def _process_effect_monos(self, module_ast):
        """Build every queued generic instantiation (design 70): clone its pristine
        template, substitute the concrete type args, register + splice it into the
        entry AST, and re-check its body so it gets its OWN effect node keyed by the
        mangled symbol. Runs to a fixpoint (a clone may itself queue more monos).
        Must run AFTER all normal bodies are checked (every concrete method's
        effect node exists) and BEFORE `finalize_effects`.

        WHAT LEFT AT DESIGN 266 U3 (218c §7 stage 5, census row T5). This used to
        carry a FOURTH step: a list of deferred "polymorphic call" edges, each
        naming a TEMPLATE and a concrete argument list, materialized here into a
        caller -> instantiation edge whenever the template turned out
        effect-polymorphic — building the instance's effect node on the side
        (`_build_fn_mono(splice=False)`) because no real instance existed to
        carry one.

        Both halves of that are gone. The edge is recorded at MONOMORPHIZATION
        time now, where the instance key is known
        (`monomorphize.apply_effect_edges`), and phase 2 materializes and
        instance-checks the body, so the node it names is a real spliced
        instance's. The deferral existed only because the recording site could
        not see an instance; that is DF-295a, and design 266 is what made an
        instance exist before the effect graph settles.

        The three DRAIN loops below stay. They are not the poly machinery — they
        are the eager driven/spawn/method-generic builds design 70 and 74 need
        BEFORE the coroutine transform runs, and each was probed load-bearing.
        """
        progress = True
        while progress:
            progress = False
            # 1. Drain eagerly-queued (driven / spawn / method-generic) builds.
            while self._pending_mono:
                template_name, resolved_args, mangled = self._pending_mono.pop()
                if self._build_fn_mono(module_ast, template_name, resolved_args,
                                       mangled):
                    progress = True
            while self._pending_method_mono:
                struct_name, method_name, resolved_args, mono_name = \
                    self._pending_method_mono.pop()
                if self._build_method_mono(struct_name, method_name, resolved_args,
                                           mono_name):
                    progress = True
            while self._pending_generic_struct_method_mono:
                (struct_name, method_name, resolved_args, method_args, mono_name,
                 _recv) = self._pending_generic_struct_method_mono.pop()
                if self._build_generic_struct_method_mono(
                        struct_name, method_name, resolved_args, method_args,
                        mono_name):
                    progress = True

    def _build_fn_mono(self, module_ast, template_name, resolved_args, mangled):
        """Clone + substitute + re-check one free-function instantiation. Returns
        True if a clone was built.

        The clone is registered and appended to the entry AST so the coroutine
        transform sees it as an ordinary concrete function (and then REMOVES it,
        replacing it with a frame — so codegen never double-defines it).

        THE EFFECT-ONLY MODE IS GONE (218c §2b row T7's rider on T5, deleted by
        design 266 U3). A second, non-splicing mode existed for one caller: the
        poly-edge materialization, which needed an instantiation's effect NODE
        without a body in the program, because codegen would monomorphize the
        instantiation from the template itself and a spliced clone would have
        double-defined the symbol. Phase 2 splices every demanded instance now
        and codegen looks them up rather than building any, so there is no
        caller left that wants a node without a body."""
        if ("fn", mangled) in self._suspend_nodes:
            return False  # effect node already built (a prior pass / dual role)
        if self.namespace.has_function(mangled):
            return False
        pristine = self._pristine_generics.get(template_name)
        if pristine is None:
            # Cross-module generic template: not supported for effect re-inference
            # here (design 68 territory). Leave conservative; codegen still works.
            return False
        type_map = {tp.name: arg
                    for tp, arg in zip(pristine.type_params, resolved_args)}
        self._add_associated_type_bindings(type_map, pristine.type_params,
                                           resolved_args)
        clone = substituting_copy(pristine, type_map)
        clone.name = mangled
        clone.type_params = []
        clone.mangled_symbol = None
        clone.is_mono_instance = True   # marks a synthesized instantiation
        self._register_function(clone)
        module_ast.functions.append(clone)
        # Check the body in the TEMPLATE's home module scope (design 210 unit
        # 4) — a template naming its own module's private helper must find it
        # here, or the instantiation carries no types at all.
        #
        # design 218 unit 1.5 stage 2: ERRORS ARE REAL (this was one of the
        # four sites that deleted its own).
        with self._checking_instance(
                _instance_display(template_name, None, resolved_args, None),
                substituted_params=substituted_param_names(pristine, type_map)):
            with self._instance_check_scope(clone, type_map):
                self._check_function(clone)
        return True

    def _add_associated_type_bindings(self, type_map, type_params, resolved_args):
        """Bind each bound's ASSOCIATED TYPES for this instantiation.

        A generic body may name an associated type of one of its bounds —
        `func getItem<T: Container>(c: T) -> Item` — and `Item` is not a type
        PARAMETER, so substituting the parameters leaves it standing. The
        abstract check resolves it through the bound; the clone has no bounds
        left (`clone.type_params = []`), so without this the instance's
        signature says `-> Item` while its body returns `Int` and the instance
        check reports a mismatch in code that is correct.
        (Found by design 218 unit 1.5 stage 2, the moment those errors stopped
        being deleted. Codegen's `_instantiate_generic_function` has done
        exactly this since brief 36 — the same three lines against
        `namespace.conformances` — so this is the typechecker side catching up
        to a binding codegen already builds, not a new rule.)
        """
        from ast_nodes import TypeKind
        for tp, arg in zip(type_params or (), resolved_args or ()):
            concrete = None
            if arg is None:
                continue
            if arg.kind == TypeKind.STRUCT:
                concrete = arg.struct_name
            elif arg.kind == TypeKind.ENUM:
                concrete = arg.enum_name
            if not concrete:
                continue
            per_trait = self.namespace.conformances.get(concrete)
            if not per_trait:
                continue
            for bound in (tp.bounds or ()):
                for assoc_name, assoc_type in (per_trait.get(bound) or {}).items():
                    type_map.setdefault(assoc_name, assoc_type)

    # `_splice_fn_mono` (218c census row T8) is GONE, deleted at stage 4 with the
    # last thing that called it — the coroutine transform's C1 promotion, which
    # built its own copy of an instantiation phase 2 had already built and
    # instance-checked. Nothing splices a function instance at transform time now;
    # C1 ADOPTS phase 2's body out of the merged AST. The DF-206e lesson the
    # deleted docstring carried lives on in `_instance_check_scope`, which is the
    # one place that decides registration scope versus body-check scope.

    def _build_method_mono(self, struct_name, method_name, resolved_args, mono_name):
        """Clone + substitute + splice + re-check one method-generic instantiation
        (design 70). The concrete method is appended to the owning extension so the
        coroutine transform's Part-0c method driving finds it; re-checking stamps
        the resolved types the frame builder consumes. Errors suppressed (effect /
        annotation harvest only)."""
        entry = _first_pristine(
            self._pristine_generic_methods.get((struct_name, method_name)))
        if entry is None:
            return False
        pristine, ext = entry
        # Already materialized on the extension (a prior pass / re-entry).
        if any(getattr(m, 'name', None) == mono_name for m in ext.methods):
            return False
        type_map = {tp.name: arg
                    for tp, arg in zip(pristine.type_params, resolved_args)}
        self._add_associated_type_bindings(type_map, pristine.type_params,
                                           resolved_args)
        clone = substituting_copy(pristine, type_map)
        clone.name = mono_name
        clone.type_params = []
        clone.is_mono_instance = True
        ext.methods.append(clone)
        # design 210 unit 4: in the template's home module scope.
        # design 218 unit 1.5 stage 2: errors are real.
        with self._checking_instance(
                _instance_display(struct_name, method_name, None, resolved_args),
                substituted_params=substituted_param_names(pristine, type_map)):
            with self._instance_check_scope(clone, type_map):
                self._check_method(struct_name, clone, {})
        return True

    # ------------------------------------------------ design 206: the std seam
    def _effect_seed_std_methods(self):
        """Mint a leaf suspend node for every std METHOD that really suspends.

        std bodies are checked ONCE, by the builtin typechecker inside
        `build_builtin_namespace`, and the entry compile never sees them. So
        `_effect_call_method` records an edge to `TcpListener.accept`'s
        `Method.node_id` and that key names nothing: the fixpoint reads `None`,
        the edge propagates nothing, and a `main` (or any helper) whose ONLY
        suspension is a std method call is judged suspension-free. It is then
        lowered as if it were — `main` never reaches the entry executor, a
        helper never joins the coroutine transform's driven closure — and the
        std method's park runs OUTSIDE a frame, where `io_wait` blocks the
        executor's thread on the reactor and `yield_now` codegens to nothing at
        all. That is DF-203a and DF-203b, one bug in two costumes.

        The table comes from `sawc.build_builtin_namespace`, keyed by
        `Method.node_id` — the compiler's only node identity, preserved verbatim
        across the std cache's pickle, and exact where a `(struct, method)` name
        pair would collide with a user type of the same name. Each entry carries
        the representative REAL source the builtin graph walked to, so a sync
        violation through a std method still names the primitive it ends at.

        Only REALLY-suspending methods are seeded (`wraps_main`'s gate):
        `Vector.map` and friends "suspend" solely by the conservative
        closure-call rule, and minting nodes for those would flag every
        `sync`/`deinit` body that maps a vector. A merely-conservative std
        method keeps the design-84 treatment it already had — the
        `_std_suspending_methods` name set the coroutine transform consults
        structurally.

        Each seeded leaf carries the std method's whole CAUSE SET (design 275
        U4), not a bit: the LABEL is one representative source, for the
        diagnostic path, and `seeded_causes` is what every derivation reads, so a
        leaf answers `refused_in_thread_body` and `frame_boundary` the way the
        std body it stands for does instead of the way its one label happens to.
        """
        table = self._std_really_suspending_methods
        if not table:
            return
        for node_id, (short, label, line, causes, alt) in table.items():
            if node_id in self._suspend_nodes:
                continue
            # Representative FIRST, so a reader that strikes nothing sees the
            # label it always saw; the alternate is the source a striking reader
            # (design 242's thread body strikes `blocking`) needs to find here
            # instead of dead-ending at the leaf.
            direct = [SuspendSource(label=label, line=line)]
            if alt is not None:
                direct.append(SuspendSource(label=alt[0], line=alt[1]))
            self._suspend_nodes[node_id] = SuspendNode(
                key=node_id,
                short=short,
                desc=f"method {short}",
                line=line,
                column=1,
                source_file=None,
                direct=direct,
                seeded_causes=causes,
            )

    # -------------------------------------------------- fixpoint + diagnostics
    def finalize_effects(self):
        """Run the whole-program fixpoint, then check every sync context.

        RE-ENTRANT, and deliberately so. ENTRY POINTS (obligation 1 — this is a
        funnel, so its entries are named here):

          * `check_module`'s `is_entry` arm / `check` — the FIRST settling, over
            the abstractly-checked program. Every module's bodies have
            contributed their edges by then.
          * `sawc._prepare_codegen`, immediately after phase 2's
            monomorphization — design 218c §1a's phase 3 ("effect finalize +
            the driven/spawn classification | concrete instances included"),
            which the driver could not honour while this ran once. A spliced
            instance's body carries its OWN effect node, minted by the instance
            check; until the fixpoint runs again over the enlarged graph that
            node reads `suspends=False` however plainly the body writes
            `yield_now()`, and the coroutine transform then classifies the call
            as ordinary and erases the suspension. That is DF-258a.
          * `sawc.compile_saw` under `--runtime-build` / `--emit-docs`, where
            the entry module is checked with `is_entry=False` and nothing above
            has settled the graph.
          * `sawc.admit_declarations`, design 266's step 6 — the coroutine
            transform's synthesized declarations are checked and monomorphized
            INTO the settled program rather than triggering a second front half,
            so the graph is extended once more and settled again. This entry is
            what the re-entrancy below was actually built for: 218 stage 4a
            landed it against a driver that still re-ran everything, and 266 is
            the pass that stopped.

        Re-entry is sound because the fixpoint is MONOTONE — a node flips to
        `suspends` and never back, so a later run only ADDS. The three
        diagnostics below are not monotone in that sense, so each consults
        `_effects_reported` and speaks once per node or site.
        """
        # design 206: the entry compile never checks std bodies, so every edge to
        # a std method points at a node that does not exist. Mint those nodes
        # first — before the fixpoint reads them — or the whole analysis below is
        # computed over a graph with the io and channel primitives cut out of it.
        self._effect_seed_std_methods()

        nodes = self._suspend_nodes
        # design 275 U4: ONE walk, and every question below is a mask over it.
        # Correct for mutual recursion and SCCs (monotone class union, so the
        # loop terminates), and re-entrant for the reason the docstring gives —
        # the graph only ever GROWS between settlings, so a fresh classification
        # can only move a node up the lattice, never back down.
        answers = classify_suspensions(nodes)
        self._suspension_answers = answers
        for key, node in nodes.items():
            node.causes = answers.causes(key)

        # design 45 item 1: record whether `main` REALLY suspends -- reaches a
        # real cooperative primitive (`yield_now`/`sleep`) -- so the pipeline wraps
        # it in the entry executor. Gated to the real primitives, NOT the broader
        # `suspends` bit: the conservative "call through a non-`sync` function
        # value" source (any closure call) and the test-only `__saw_suspend` (used
        # only with explicit `__saw_drive`) must NOT auto-wrap main.
        # design 76: `__saw_io_park` (IO reactor) and blocking-extern offload are also
        # REAL suspensions that must wrap `main` in the entry executor.
        # design 206: the gate reads the executor question — one definition,
        # shared with the builtin compile that supplies the std method table, and
        # since design 275 U4 a derived read of the analysis above rather than a
        # walk of its own.
        self._main_suspends = answers.wraps_main(("fn", "main"))

        # design 260: the two fences a SUSPENDING consuming body meets. Decided
        # here because "does this body suspend?" is a whole-program answer.
        self._check_consumes_suspending_fences(nodes)

        # design 242 ruling 9: a blocking-permitted context asks a narrower
        # question. Both narrowings below are DERIVED READS of the one analysis
        # now (design 275 U4) — they used to be a second and a third fixpoint,
        # computed lazily because each cost a whole pass over the graph.
        for node in nodes.values():
            if not (node.sync_reason and node.suspends):
                continue
            if (node.blocking_permitted
                    and not answers.refused_in_thread_body(node.key)):
                continue
            # SL-306 review r2: a SYNTHESIZED frame method asks the narrower
            # question, for the reason `closure_calls_permitted` states — the
            # framing question.
            if node.closure_calls_permitted and not answers.frame_boundary(node.key):
                continue
            if ("sync", node.key) in self._effects_reported:
                continue
            self._effects_reported.add(("sync", node.key))
            self._report_sync_violation(node)

        self._report_existential_suspend_dispatch(answers)

    def _report_existential_suspend_dispatch(self, answers):
        """design 223 unit 3 (DF-223b): refuse a dispatch through `any Trait` to
        a trait method some conformance implements with a SUSPENDING body.

        The refusal is the whole answer this brief has for that cell, and the
        reason is structural rather than temporary: the caller of a suspending
        method embeds the callee's FRAME BY VALUE, so it must know at compile
        time which body it is embedding, and a vtable word is exactly the thing
        that withholds that. Making it work is a design (three candidate answers
        are written out at DF-223b), not a fix.

        What it replaces is worse than a refusal: no frame was built anywhere,
        so the `yield_now()` inside the impl ran outside any frame — where it is
        a no-op — and the program compiled, printed the right answer and never
        ceded to a sibling. Anchored at the DISPATCH, which is the line an
        author can act on.
        """
        for site in self._existential_dispatch_sites:
            trait_name, method_name, line, column, src = site
            impls = self._trait_impl_nodes.get((trait_name, method_name), ())
            for node_id, owner in impls:
                # The EXECUTOR question (`wraps_main`, design 206's old
                # `really_suspending`): a conformance body whose only suspension
                # is the test-only `__saw_suspend` is not refused here, exactly
                # as before.
                if not answers.wraps_main(node_id):
                    continue
                if ("existential", site) in self._effects_reported:
                    break
                self._effects_reported.add(("existential", site))
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot dispatch through `any {trait_name}` to "
                    f"`{method_name}`: `{owner}` implements it with a "
                    f"SUSPENDING body, and a suspending call needs the callee's "
                    f"frame at compile time — dynamic dispatch has only a vtable "
                    f"word, so there is no frame to embed and nothing to drive",
                    line, column,
                    hint=f"call `{method_name}` on the concrete type, or take "
                         f"the receiver as a generic `<T: {trait_name}>` (which "
                         f"monomorphizes and keeps the frame identity). Erasing "
                         f"a suspending method is unimplemented by design, not "
                         f"by accident — see DF-223b",
                    source_file=src)
                break

    def _report_sync_violation(self, node: SuspendNode):
        hops, susp_short, susp_line = self._effect_path(
            node, skip_blocking=node.blocking_permitted)
        chain = " → ".join(hops)
        msg = (f"cannot suspend in {node.sync_reason}: {node.desc} "
               f"calls {chain} ({susp_short} suspends at line {susp_line})")
        self.reporter.error(
            ErrorKind.TYPE_MISMATCH, msg, node.line, node.column,
            hint=node.sync_hint or (
                "a `sync` context must be transitively suspension-free: remove "
                "the suspending call or hoist it out of the sync region"),
            source_file=node.source_file,
        )

    def _effect_path(self, node: SuspendNode,
                     skip_blocking: bool = False) -> Tuple[List[str], str, int]:
        """One representative path from `node` to a suspension source.

        Returns (hops, suspending_node_short, source_line) where `hops` is the
        chain of callee short-names ending in the source label.

        `skip_blocking` walks past blocking-extern sources (design 242 ruling 9):
        in a blocking-permitted context those are legal, so a path that names one
        would point at the wrong line — the reader needs the cooperative
        suspension that actually broke the rule.

        A SEEDED std leaf is why `direct` may hold more than one source: a std
        method with several causes carries one per cause (design 275 U4), in
        representative-first order, so `own[0]` below is the same label every
        non-striking reader has always seen while a striking one still finds the
        source that satisfies its own question. Without that second source the
        walk dead-ends at the leaf and falls to `PATH_PLACEHOLDER_LABEL`, which
        is what `Thread.spawn { c.output() }` printed.
        """
        visited = set()

        def sources(n: SuspendNode):
            if not skip_blocking:
                return n.direct
            return [s for s in n.direct
                    if not _source_class(s) & SuspendCause.BLOCKING]

        def walk(n: SuspendNode):
            visited.add(n.key)
            own = sources(n)
            if own:
                src = own[0]
                return ([src.label], n.short, src.line)
            for e in n.edges:
                t = self._suspend_nodes.get(e.target)
                if t is not None and t.suspends and t.key not in visited:
                    sub = walk(t)
                    if sub is not None:
                        hops, susp_short, susp_line = sub
                        return ([t.short] + hops, susp_short, susp_line)
            return None

        result = walk(node)
        if result is None:
            # Should not happen for a suspending node, but stay robust. A reader
            # that CONSTRUCTS a path for a table (the std seed) tests for this
            # label rather than shipping it into a user-facing message.
            return ([PATH_PLACEHOLDER_LABEL], node.short, node.line)
        return result

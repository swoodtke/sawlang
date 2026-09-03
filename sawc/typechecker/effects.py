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
                       "__saw_chan_park")


_BLOCKING_SOURCE_PREFIX = "blocking extern"


def _is_real_source(source: SuspendSource) -> bool:
    return (source.label in REAL_SUSPEND_LABELS
            or source.label.startswith(_BLOCKING_SOURCE_PREFIX))


def suspends_ignoring_blocking(nodes) -> Dict[Any, bool]:
    """`suspends`, computed with every BLOCKING-EXTERN source struck out.

    The question design 242 ruling 9's blocking-permitted context asks: a
    `Thread.spawn { ... }` body may block its own thread on FFI (that is the
    point of spawning one), and must still be refused every OTHER way of
    suspending — a cooperative primitive, a park, a suspending callee — because
    there is no executor on that thread to resume it.

    Same shape as the `suspends` fixpoint and as `really_suspending`: monotone,
    SCC-safe, and computed once per finalize. Blocking-ness is a property of the
    SOURCE, so a helper the body calls is struck out on the same terms — which
    is what makes `Thread.spawn { drain(fd) }` legal for a `drain` written
    around a `blocking` extern.
    """
    out: Dict[Any, bool] = {}
    for key, node in nodes.items():
        out[key] = any(not s.label.startswith(_BLOCKING_SOURCE_PREFIX)
                       for s in node.direct)
    changed = True
    while changed:
        changed = False
        for key, node in nodes.items():
            if out.get(key):
                continue
            for e in node.edges:
                if out.get(e.target):
                    out[key] = True
                    changed = True
                    break
    return out


def really_suspending(nodes) -> Dict[Any, bool]:
    """THE answer to "does this body REALLY suspend?", for every node in `nodes`.

    Design 206's funnel: one definition, two typecheckers. Both callers below
    ask the same question of the same graph shape, and the two used to differ —
    which is the whole of DF-203a/DF-203b.

    ENTRY POINTS (every caller; process rule 1):
      * `EffectsMixin.finalize_effects` — the ENTRY compile, for `_main_suspends`
        (the design-45 item-1 gate that wraps a suspending `main` in the entry
        executor).
      * `sawc.build_builtin_namespace` — the BUILTIN compile, for
        `_std_really_suspending_methods`, the table the entry compile is then
        seeded with (`EffectsMixin._effect_seed_std_methods`). std bodies are
        checked only there, so without the table the entry graph believes
        `listener.accept()` and `ch.receive()` suspend nothing.

    ROUTES a real suspension travels to reach a body (the position matrix this
    answer quantifies over):
      1. a direct cooperative primitive in the body — `yield_now()` /
         `sleep(d)` / `io_wait(fd, dir)` / `__saw_io_park()`;
      2. a `blocking` extern call (design 103's thread offload);
      3. a call to another analyzed body that reaches 1-3 (any depth, SCC-safe);
      4. a call to a std METHOD that reaches 1-3 — carried in as a seeded leaf
         node, because std bodies belong to a different typechecker's graph.
    The conservative closure source is deliberately NOT a route: it says
    "might", and this question is "does".
    """
    really: Dict[Any, bool] = {}
    for key, node in nodes.items():
        really[key] = any(_is_real_source(s) for s in node.direct)
    changed = True
    while changed:
        changed = False
        for key, node in nodes.items():
            if really.get(key):
                continue
            for e in node.edges:
                if really.get(e.target):
                    really[key] = True
                    changed = True
                    break
    return really


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
    direct: List[SuspendSource] = field(default_factory=list)
    edges: List[SuspendEdge] = field(default_factory=list)
    suspends: bool = False              # computed by the fixpoint
    # design 70 (A5): set when this body calls a method on a type-PARAMETER
    # receiver (`w.step()` for `w: T`). Such a body's suspendability is
    # effect-polymorphic — it depends on the concrete `T` — so a call to this
    # generic function with concrete type args triggers per-INSTANTIATION effect
    # re-inference (monomorphize + re-check the body with `T` bound).
    poly_candidate: bool = False


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
        # design 206: the std METHODS that REALLY suspend, as
        # `Method.node_id -> (short, real-source label, line)`. Empty here and
        # filled by the driver out of the builtin namespace (`sawc.py`), because
        # only the builtin typechecker ever analyzes a std body. Empty is the
        # right default for the BUILTIN compile itself, which has those bodies in
        # front of it. `_effect_seed_std_methods` mints a leaf node per entry.
        self._std_really_suspending_methods: Dict[Any, tuple] = {}
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
        # Deferred potential effect edges from a generic CALL with concrete type
        # args to its instantiation node: (caller_node_key, template_name,
        # resolved_type_args, short, line). Materialized into real edges (after
        # building the instantiation) only when the template is effect-polymorphic.
        self._poly_call_edges: List[Any] = []
        # design 223 unit 3 (DF-223b). A frame is a COMPILE-TIME identity — the
        # caller embeds the callee's frame by value — and dynamic dispatch has
        # none, so a suspending conformance body reached through `any Trait` can
        # neither be embedded nor driven. It was not refused either: the dispatch
        # is a merely-CONSERVATIVE suspension source (`really_suspending`
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
        key = ("fn", getattr(func, 'mangled_symbol', None) or func.name)
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
            key_name = getattr(func_info, "mangled_name", "") or name
            self._effect_add_edge(("fn", key_name), f"`{name}`", line)

    def _effect_call_method(self, method_info, short: str, line: int):
        ast = getattr(method_info, "ast_node", None)
        if ast is not None:
            self._effect_add_edge(ast.node_id, short, line)

    def _effect_indirect_call(self, func_type, line: int):
        """A call through a function-typed value. Non-`sync` => conservatively
        suspends (design 22 known-hard case: effect polymorphism)."""
        if not getattr(func_type, "func_is_sync", False):
            self._effect_direct_source(
                "a call through a non-`sync` function value", line)

    # ---------------------------------------------- design 70: effect polymorphism
    def _effect_mark_poly(self):
        """Flag the current body as effect-polymorphic (it calls a method on a
        type-parameter receiver, so its suspendability depends on the concrete
        binding — re-inferred per instantiation)."""
        node = self._effect_current()
        if node is not None:
            node.poly_candidate = True

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

    def _effect_record_poly_call(self, template_name: str, resolved_args,
                                 short: str, line: int):
        """Record a deferred potential effect edge from the current body to the
        instantiation `template_name<args>`. Materialized (and the instantiation
        built) at finalize time ONLY if the template turns out effect-polymorphic,
        so ordinary generic calls (identity/map/…) are untouched."""
        node = self._effect_current()
        if node is None or node.key is None:
            return
        self._poly_call_edges.append(
            (node.key, template_name, list(resolved_args), short, line))

    def _process_effect_monos(self, module_ast):
        """Build every queued generic instantiation (design 70): clone its pristine
        template, substitute the concrete type args, register + splice it into the
        entry AST, and re-check its body so it gets its OWN effect node keyed by the
        mangled symbol. Runs to a fixpoint (a clone may itself queue more monos or
        record more polymorphic calls). Must run AFTER all normal bodies are checked
        (every concrete method's effect node exists) and BEFORE `finalize_effects`.
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
            # 2. Materialize polymorphic call edges whose template is poly. Build
            #    the instantiation, then add a real edge caller -> instantiation.
            #    Snapshot + clear first: a clone's re-check may append NEW edges,
            #    which accumulate for the next fixpoint round (not this one).
            edges, self._poly_call_edges = self._poly_call_edges, []
            for (caller_key, template_name, resolved_args, short, line) in edges:
                tmpl_node = self._suspend_nodes.get(("fn", template_name))
                if tmpl_node is None or not tmpl_node.poly_candidate:
                    continue  # ordinary generic call — leave conservative behavior
                from codegen.mangle import mangle_function
                mangled = mangle_function(template_name, resolved_args)
                if ("fn", mangled) not in self._suspend_nodes:
                    # Effect-only build: create the instantiation's suspend node
                    # WITHOUT splicing it (codegen still monomorphizes it from the
                    # template — a spliced clone would double-define the symbol).
                    self._build_fn_mono(module_ast, template_name, resolved_args,
                                        mangled, splice=False)
                    progress = True
                caller = self._suspend_nodes.get(caller_key)
                if caller is not None and not any(
                        e.target == ("fn", mangled) for e in caller.edges):
                    caller.edges.append(SuspendEdge(
                        target=("fn", mangled), short=short, line=line))

    def _build_fn_mono(self, module_ast, template_name, resolved_args, mangled,
                       splice=True):
        """Clone + substitute + re-check one free-function instantiation. Returns
        True if a clone was built. Errors from the re-check are SUPPRESSED — this
        pass only harvests effect edges; genuine instantiation errors surface
        through the normal codegen monomorphization path.

        `splice=True` (driven / spawn roots) registers the clone and appends it to
        the entry AST so the coroutine transform sees it as an ordinary concrete
        function (and then REMOVES it, replacing it with a frame — so codegen never
        double-defines it). `splice=False` (an effect-polymorphic plain call) only
        creates the effect node: the instantiation stays codegen's job (from the
        template), so the clone must NOT be left in the AST / namespace."""
        if ("fn", mangled) in self._suspend_nodes:
            return False  # effect node already built (a prior pass / dual role)
        if splice and self.namespace.has_function(mangled):
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
        if splice:
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

        Only REALLY-suspending methods are seeded (`really_suspending`'s gate):
        `Vector.map` and friends "suspend" solely by the conservative
        closure-call rule, and minting nodes for those would flag every
        `sync`/`deinit` body that maps a vector. A merely-conservative std
        method keeps the design-84 treatment it already had — the
        `_std_suspending_methods` name set the coroutine transform consults
        structurally.
        """
        table = self._std_really_suspending_methods
        if not table:
            return
        for node_id, (short, label, line) in table.items():
            if node_id in self._suspend_nodes:
                continue
            self._suspend_nodes[node_id] = SuspendNode(
                key=node_id,
                short=short,
                desc=f"method {short}",
                line=line,
                column=1,
                source_file=None,
                direct=[SuspendSource(label=label, line=line)],
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
        # Iterate to fixpoint. Correct for mutual recursion and SCCs: a node
        # flips to `suspends` once any source or any suspending callee is seen,
        # and flips are monotone, so the loop terminates in <= |nodes| sweeps.
        changed = True
        while changed:
            changed = False
            for node in nodes.values():
                if node.suspends:
                    continue
                s = bool(node.direct)
                if not s:
                    for e in node.edges:
                        t = nodes.get(e.target)
                        if t is not None and t.suspends:
                            s = True
                            break
                if s:
                    node.suspends = True
                    changed = True

        # design 45 item 1: record whether `main` REALLY suspends -- reaches a
        # real cooperative primitive (`yield_now`/`sleep`) -- so the pipeline wraps
        # it in the entry executor. Gated to the real primitives, NOT the broader
        # `suspends` bit: the conservative "call through a non-`sync` function
        # value" source (any closure call) and the test-only `__saw_suspend` (used
        # only with explicit `__saw_drive`) must NOT auto-wrap main.
        # design 76: `__saw_io_park` (IO reactor) and blocking-extern offload are also
        # REAL suspensions that must wrap `main` in the entry executor.
        # design 206: the gate reads `really_suspending` — the ONE definition,
        # shared with the builtin compile that supplies the std method table.
        self._main_suspends = bool(really_suspending(nodes).get(("fn", "main")))

        # design 260: the two fences a SUSPENDING consuming body meets. Decided
        # here because "does this body suspend?" is a whole-program answer.
        self._check_consumes_suspending_fences(nodes)

        # design 242 ruling 9: a blocking-permitted context asks a narrower
        # question, so the second fixpoint is computed only if one exists.
        beyond_blocking = None
        for node in nodes.values():
            if not (node.sync_reason and node.suspends):
                continue
            if node.blocking_permitted:
                if beyond_blocking is None:
                    beyond_blocking = suspends_ignoring_blocking(nodes)
                if not beyond_blocking.get(node.key):
                    continue
            if ("sync", node.key) in self._effects_reported:
                continue
            self._effects_reported.add(("sync", node.key))
            self._report_sync_violation(node)

        self._report_existential_suspend_dispatch(really_suspending(nodes))

    def _report_existential_suspend_dispatch(self, really):
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
                if not really.get(node_id):
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
        """
        visited = set()

        def sources(n: SuspendNode):
            if not skip_blocking:
                return n.direct
            return [s for s in n.direct
                    if not s.label.startswith(_BLOCKING_SOURCE_PREFIX)]

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
            # Should not happen for a suspending node, but stay robust.
            return (["<suspension source>"], node.short, node.line)
        return result

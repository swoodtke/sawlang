"""
design 22 — `sync` effect system prototype (the flip, investigated early).

Whole-program transitive suspendability inference plus `sync`-context checking.

Model (design 18 Axis B'): calls are COLORLESS — any call may suspend. The
marker sits on the rare side: `sync` is a checked negative effect. A
function / method / closure "suspends" iff its body transitively reaches a
suspension source:

  * the `__test_suspend()` intrinsic (synthetic suspension point),
  * a call to an `extern blocking func` (unbounded FFI),
  * a call to a suspending function/method (transitive), or
  * a call THROUGH a non-`sync` function-typed value (conservative — this is
    where effect polymorphism bites; see designs/22-findings.md).

A `sync` context — a `sync func`, a `deinit` body, or a value whose target
type is a `sync (...)` function type (e.g. `Mutex.lock`'s closure parameter) —
must be transitively suspension-free. A violation is reported with the full
suspension PATH: `... closure calls f -> g -> __test_suspend (g suspends at
line N)`.

Implementation strategy: the call graph is collected DURING type checking
(reusing the checker's name/type resolution), keyed by AST identity, into
instance state on the TypeChecker. After all bodies are checked, a single
iterate-to-fixpoint pass computes each node's `suspends` bit (SCC-correct for
mutual recursion), then every sync context is checked and diagnosed.

Scope guard: no executor, no state machines, no async/await. `__test_suspend`
codegens to a no-op; this pass is pure typechecker machinery.
"""

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from errors import ErrorKind


def substitute_ast_types(node, type_map):
    """In-place: rewrite every `SawType` in an AST subtree through
    `SawType.substitute(type_map)` (design 70). Used to monomorphize a pristine
    generic function template into a concrete instantiation for per-instantiation
    effect re-inference. `SawType.substitute` recurses through nested type
    structure, so this walker only has to reach each SawType-valued field once.
    Walks any dataclass node (AST nodes, `Parameter`, `Argument`, `StructField`,
    …) but treats a `SawType` itself as a leaf (handled by `_subst_ast_value`).
    """
    from ast_nodes import SawType
    if not dataclasses.is_dataclass(node) or isinstance(node, (SawType, type)):
        return
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


@dataclass
class SuspendSource:
    """A place where a node suspends without going through another node."""
    label: str   # e.g. "__test_suspend", "blocking extern `read`"
    line: int


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
        # Keyed by ("fn", name) for free functions, id(Method) for methods,
        # and id(ClosureExpr) for closures.
        self._suspend_nodes: Dict[Any, SuspendNode] = {}
        self._suspend_stack: List[SuspendNode] = []
        # design 44: free-function names driven by a `__drive(...)` /
        # `__drive_steps(...)` site, mapped to the set of driver modes requested
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
        # `TaskHandle<T>`) — but no `__drive_*` driver.
        self._spawn_roots: Dict[str, Any] = {}
        # design 70 (A5): effect polymorphism via monomorphization-time
        # re-inference. Pristine (pre-body-check) copies of every generic function
        # template, keyed by name, so an instantiation can be cloned + substituted
        # + re-checked to get its OWN effect node keyed by the mangled symbol.
        self._pristine_generics: Dict[str, Any] = {}
        # Queued instantiation builds: list of (template_name, resolved_type_args,
        # mangled). Driven / spawned / method-generic roots queue eagerly (the
        # mangled name is needed at the site to rewrite the call); the build (clone
        # + re-check) is deferred to `_process_effect_monos`.
        self._pending_mono: List[Any] = []
        self._mono_built: set = set()   # mangled symbols already built/queued
        # Method-generic instantiations (design 70): pristine templates keyed by
        # (struct_name, method_name) -> (Method, owning Extension), and queued
        # concrete builds (struct_name, method_name, resolved_args, mono_name).
        self._pristine_generic_methods: Dict[Any, Any] = {}
        self._pending_method_mono: List[Any] = []
        # design 74 (A5-rest, shape 2): pristine methods on GENERIC-struct
        # extensions, keyed by (struct_name, method_name) -> (Method, Extension).
        # A driven `__drive(b.run())` with `b: Holder<Int>` monomorphizes the
        # method over the struct's type params and records the concrete driven
        # method here (keyed by a per-instantiation mono method name), carrying the
        # concrete receiver SawType (`Holder<Int>`) the frame's `__recv` needs.
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

    def _effect_record_driven(self, name: str, mode: str):
        self._driven_roots.setdefault(name, set()).add(mode)

    def _effect_record_spawn(self, name: str, return_type):
        self._spawn_roots[name] = return_type

    def _effect_record_driven_method(self, struct_name: str, method: str, mode: str):
        self._driven_method_roots.setdefault((struct_name, method), set()).add(mode)

    def _effect_absorb_scope(self):
        """A context manager-ish pair: push a throwaway suspend node so effect
        edges recorded while checking a `__drive` argument attach to it (and are
        discarded) rather than to the enclosing function — the driver ABSORBS the
        callee's suspension (like `block_on`), so `__drive`'s caller does not
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
        key = id(method)
        node = self._suspend_nodes.get(key)
        if node is None:
            mname = getattr(method, "name", "?")
            is_deinit = (mname == "deinit")
            is_sync = getattr(method, "is_sync", False)
            reason = None
            if is_deinit:
                reason = "`deinit` context"
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
            )
            self._suspend_nodes[key] = node
        self._suspend_stack.append(node)
        return node

    def _effect_enter_closure(self, closure, expected_type):
        key = id(closure)
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
            self._effect_add_edge(id(ast), short, line)

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
            self, struct_name, method_name, resolved_args, mono_name, recv_type):
        """design 74 (A5-rest, shape 2): queue a build of a driven suspending
        method on a GENERIC struct, monomorphized over the struct's type params for
        a concrete receiver (`Holder<Int>`). Returns False if no pristine template
        is known (e.g. the method lives in another module — not supported here).
        Records the concrete receiver SawType eagerly (the frame's `__recv` needs
        it); the clone+re-check is deferred to `_process_effect_monos`."""
        if (struct_name, method_name) not in self._pristine_generic_struct_methods:
            return False
        key = (struct_name, mono_name)
        if key not in self._driven_generic_struct_methods:
            # Clone filled in by the deferred build; recv_type known now.
            self._driven_generic_struct_methods[key] = (recv_type, None)
            self._pending_generic_struct_method_mono.append(
                (struct_name, method_name, list(resolved_args), mono_name, recv_type))
        return True

    def _build_generic_struct_method_mono(self, struct_name, method_name,
                                          resolved_args, mono_name):
        """Clone + substitute (struct type params) + re-check one generic-struct
        driven method (design 74 shape 2). The concrete method is NOT spliced onto
        an extension (its `self` is `Holder<Int>`, which a plain non-generic
        extension can't express); it is stored for the coroutine transform, which
        builds the frame with `__recv: UnsafePointer<Holder<Int>>` from it. The
        re-check stamps the resolved (concrete) types the frame builder consumes.
        Errors suppressed (effect / annotation harvest only)."""
        import copy
        key = (struct_name, mono_name)
        recv_type, existing = self._driven_generic_struct_methods.get(key, (None, None))
        if existing is not None:
            return False
        entry = self._pristine_generic_struct_methods.get((struct_name, method_name))
        if entry is None:
            return False
        pristine, ext = entry
        tps = ext.type_params or []
        clone = copy.deepcopy(pristine)
        type_map = {tp.name: arg for tp, arg in zip(tps, resolved_args)}
        substitute_ast_types(clone, type_map)
        clone.name = mono_name
        clone.type_params = []
        clone.is_mono_instance = True
        saved_errors = len(self.reporter.errors)
        saved_warnings = len(self.reporter.warnings)
        # type_subst binds `self` to `Holder<Int>` so field access through `self`
        # resolves the struct's `T`-typed fields to their concrete types.
        self._check_method(struct_name, clone, type_map)
        del self.reporter.errors[saved_errors:]
        del self.reporter.warnings[saved_warnings:]
        # The re-check stamps `resolved_type` on the body's expressions, but member
        # access through `self` resolves the struct's `T`-typed fields to `T` (the
        # generic StructSymbol carries `T`, and `_resolve_type` doesn't apply the
        # method's type_subst to a bare type param). Substitute AGAIN over the
        # stamped types so a frame local like `let before = self.value` gets the
        # concrete field type (Int) the frame layout needs — not `T`.
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
                (struct_name, method_name, resolved_args, mono_name, _recv) = \
                    self._pending_generic_struct_method_mono.pop()
                if self._build_generic_struct_method_mono(
                        struct_name, method_name, resolved_args, mono_name):
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
        import copy
        if ("fn", mangled) in self._suspend_nodes:
            return False  # effect node already built (a prior pass / dual role)
        if splice and self.namespace.has_function(mangled):
            return False
        pristine = self._pristine_generics.get(template_name)
        if pristine is None:
            # Cross-module generic template: not supported for effect re-inference
            # here (design 68 territory). Leave conservative; codegen still works.
            return False
        clone = copy.deepcopy(pristine)
        type_map = {tp.name: arg
                    for tp, arg in zip(pristine.type_params, resolved_args)}
        substitute_ast_types(clone, type_map)
        clone.name = mangled
        clone.type_params = []
        clone.mangled_symbol = None
        clone.is_mono_instance = True   # marks a synthesized instantiation
        if splice:
            self._register_function(clone)
            module_ast.functions.append(clone)
        # Re-check the body with errors suppressed (effect harvest only).
        saved_errors = len(self.reporter.errors)
        saved_warnings = len(self.reporter.warnings)
        self._check_function(clone)
        del self.reporter.errors[saved_errors:]
        del self.reporter.warnings[saved_warnings:]
        return True

    def _splice_fn_mono(self, module_ast, template_name, resolved_args, mangled):
        """design 74 (A5-rest, shape 3): splice a concrete instantiation of a
        generic free function into the AST + namespace and re-check it (so its body
        carries the resolved types the coroutine frame builder consumes), returning
        True on a fresh splice. Unlike `_build_fn_mono`, this runs AFTER the effect
        fixpoint (from the coroutine transform) to promote a NESTED suspending
        generic call to a real concrete callee that gets its own frame. Idempotent
        by namespace presence; the effect node may already exist (built effect-only
        during checking) — re-checking just re-stamps types and re-adds edges
        (harmless post-fixpoint). Returns False if the template isn't in this module
        (cross-module is shape 4) or the symbol is already present."""
        import copy
        if self.namespace.has_function(mangled):
            return False
        pristine = self._pristine_generics.get(template_name)
        if pristine is None:
            return False
        clone = copy.deepcopy(pristine)
        type_map = {tp.name: arg
                    for tp, arg in zip(pristine.type_params, resolved_args)}
        substitute_ast_types(clone, type_map)
        clone.name = mangled
        clone.type_params = []
        clone.mangled_symbol = None
        clone.is_mono_instance = True
        # Restore the entry module's symbol scope for registration + re-check (the
        # namespace was reset after check_module returned; a fresh check under the
        # wrong scope would silently fail to resolve types and leave locals
        # untyped, which the frame builder needs).
        saved_ns = self.namespace
        saved_path = getattr(self, 'current_module_path', None)
        entry_ns = getattr(self, '_entry_module_ns', None)
        if entry_ns is not None:
            self.namespace = entry_ns
            self.current_module_path = getattr(self, '_entry_module_path', saved_path)
        saved_errors = len(self.reporter.errors)
        saved_warnings = len(self.reporter.warnings)
        try:
            self._register_function(clone)
            module_ast.functions.append(clone)
            self._check_function(clone)
        finally:
            del self.reporter.errors[saved_errors:]
            del self.reporter.warnings[saved_warnings:]
            self.namespace = saved_ns
            self.current_module_path = saved_path
        return clone

    def _build_method_mono(self, struct_name, method_name, resolved_args, mono_name):
        """Clone + substitute + splice + re-check one method-generic instantiation
        (design 70). The concrete method is appended to the owning extension so the
        coroutine transform's Part-0c method driving finds it; re-checking stamps
        the resolved types the frame builder consumes. Errors suppressed (effect /
        annotation harvest only)."""
        import copy
        entry = self._pristine_generic_methods.get((struct_name, method_name))
        if entry is None:
            return False
        pristine, ext = entry
        # Already materialized on the extension (a prior pass / re-entry).
        if any(getattr(m, 'name', None) == mono_name for m in ext.methods):
            return False
        clone = copy.deepcopy(pristine)
        type_map = {tp.name: arg
                    for tp, arg in zip(pristine.type_params, resolved_args)}
        substitute_ast_types(clone, type_map)
        clone.name = mono_name
        clone.type_params = []
        clone.is_mono_instance = True
        ext.methods.append(clone)
        saved_errors = len(self.reporter.errors)
        saved_warnings = len(self.reporter.warnings)
        self._check_method(struct_name, clone, {})
        del self.reporter.errors[saved_errors:]
        del self.reporter.warnings[saved_warnings:]
        return True

    # -------------------------------------------------- fixpoint + diagnostics
    def finalize_effects(self):
        """Run the whole-program fixpoint, then check every sync context.

        Idempotent: guarded so it runs once even if both the single-file and
        module entry paths call it.
        """
        if getattr(self, "_effects_finalized", False):
            return
        self._effects_finalized = True

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
        # value" source (any closure call) and the test-only `__suspend` (used
        # only with explicit `__drive`) must NOT auto-wrap main.
        real_labels = ("yield_now", "sleep")
        really = {}
        for key, node in nodes.items():
            really[key] = any(s.label in real_labels for s in node.direct)
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
        self._main_suspends = bool(really.get(("fn", "main")))

        for node in nodes.values():
            if node.sync_reason and node.suspends:
                self._report_sync_violation(node)

    def _report_sync_violation(self, node: SuspendNode):
        hops, susp_short, susp_line = self._effect_path(node)
        chain = " → ".join(hops)
        msg = (f"cannot suspend in {node.sync_reason}: {node.desc} "
               f"calls {chain} ({susp_short} suspends at line {susp_line})")
        self.reporter.error(
            ErrorKind.TYPE_MISMATCH, msg, node.line, node.column,
            hint="a `sync` context must be transitively suspension-free: remove "
                 "the suspending call or hoist it out of the sync region",
            source_file=node.source_file,
        )

    def _effect_path(self, node: SuspendNode) -> Tuple[List[str], str, int]:
        """One representative path from `node` to a suspension source.

        Returns (hops, suspending_node_short, source_line) where `hops` is the
        chain of callee short-names ending in the source label.
        """
        visited = set()

        def walk(n: SuspendNode):
            visited.add(n.key)
            if n.direct:
                src = n.direct[0]
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

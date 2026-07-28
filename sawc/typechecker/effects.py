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

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from errors import ErrorKind


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


class EffectsMixin:
    """Mixed into TypeChecker; owns the design-22 suspend analysis."""

    # ------------------------------------------------------------------ setup
    def _effect_init(self):
        # Keyed by ("fn", name) for free functions, id(Method) for methods,
        # and id(ClosureExpr) for closures.
        self._suspend_nodes: Dict[Any, SuspendNode] = {}
        self._suspend_stack: List[SuspendNode] = []

    # ------------------------------------------------------- node entry / exit
    def _effect_enter_function(self, func):
        key = ("fn", func.name)
        node = self._suspend_nodes.get(key)
        if node is None:
            is_sync = getattr(func, "is_sync", False)
            node = SuspendNode(
                key=key,
                short=f"`{func.name}`",
                desc=(f"`sync func {func.name}`" if is_sync
                      else f"function `{func.name}`"),
                line=func.line,
                column=func.column,
                source_file=getattr(func, "source_file", None),
                sync_reason=("`sync func` declaration" if is_sync else None),
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
            self._effect_add_edge(("fn", name), f"`{name}`", line)

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

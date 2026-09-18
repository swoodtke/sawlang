"""THE key that names a free function's coroutine frame (SL-280).

One question — *what key names this callee's frame?* — asked by the effect
graph, by the coroutine transform's body tables, by the closure walk, and by
every call-site classifier. Before SL-280 it was answered independently in six
places and they disagreed: three read the AST's plain `name` while three read
`mangled_symbol or name`, and design 249 gives a module-PRIVATE free function a
`$m$<module>` tag that a `public` one does not carry. So the graph's edge key
`read_chunk$m$src_http` never matched the table key `read_chunk`, the closure
walk declined the edge with no diagnostic, no frame was built for the callee or
for anything below it, and codegen's out-of-frame park fallback blocked the
cooperative executor's own thread — the whole process wedged on one idle socket.

The answer here is INDEPENDENT of whether a free function happens to carry a
tag. A declaration, a call site and a resolved symbol all name the same frame,
so they all produce the same string, and a program where the tag is present
behaves exactly as one where it is absent. That independence is the point, and
SL-274 collected on it: EVERY free function outside std now carries a
`$m$<module>` tag, so the agreement between a public function's bare name and
its key — a coincidence before — is gone, and every site that read a written
name had to be one of the entries below.

ENTRY POINTS (obligation 1 — a funnel names its entries):

  * `typechecker/effects.py::_effect_enter_function` — the effect graph's NODE
    key for a free-function definition (`("fn", <key>)`).
  * `typechecker/effects.py::_effect_call_function` — the effect graph's EDGE
    key for a resolved free call, bare or module-qualified.
  * `coro_transform.py::transform_program` — `funcs_by_name`, the entry
    module's body table, and `imported_free_fns`, the importable-body table the
    SL-208 splice draws from (including the shadow-out test between them).
  * `coro_transform.py::_splice_imported_free_fn` — the key a spliced clone is
    registered under, and the key `removed`/`program.functions` filter it back
    out by once its frame exists.
  * `coro_transform.py::_FrameBuilder.name` — the frame's own identity, hence
    `__Frame_<key>`, `__saw_drive_<key>` and `__spawn_<key>`.
  * `coro_transform.py::_FrameBuilder._classify_call` — the call-site
    classifier's `self._suspends` membership test AND the `callee` it emits,
    which `_callee_fb` then resolves against `fbs`.
  * `coro_transform.py::_FrameBuilder._classify_method_call` and
    `_module_free_call_suspends` — the same two questions for SL-208's
    module-qualified free call, which wears a `MethodCall`'s shape.
  * `coro_transform.py::_promote_nested_generic_methods` — the free-fn descent
    of the method-instantiation walk (`funcs_by_name` again).
  * `coro_transform.py::_promote_nested_generic_calls` — the TEMPLATE base a
    nested generic call's instantiation is spelled from
    (`mangle_function(<key>, args)`), so the instance this walk names is the
    instance `monomorphize._function_template_name` demanded; and the CLEAR of
    the stale `resolved_symbol` once the call has been rewritten to name that
    instance. Added by SL-274, which is what made a generic callee's base and
    its written name differ for every module.
  * `coro_transform.py::_FrameBuilder._is_suspending_expr` — the ANF /
    expression-position hoist's suspension test.
  * `coro_transform.py::_FrameBuilder._spans_suspension` — the CFG-split test.
  * `coro_transform.py::_FrameBuilder._reject_buried_suspend_call` — the
    inexpressible-position refusal.
  * `coro_transform.py::_default_expr_suspends` — a defaulted argument's
    suspension test.
  * `coro_transform.py::_rewrite_drive_sites` — the driver a `__saw_drive`
    site is rewritten to.
  * `coro_transform.py::_called_function_names` and
    `_consume_templates_naming_removed` — the consumption sweep, which
    intersects "what the survivors call" with `removed`.
  * `typechecker/expressions.py` — the driven-root recording
    (`_effect_record_driven`) and the spawn-root recording
    (`_check_spawned_call_argument`), so `roots`/`spawn_roots` live in the same
    key space as the tables the transform looks them up in.

NOT an entry point, deliberately: a METHOD frame, whose key is
`coro_transform.py::_method_frame_key` (`{struct}_{method}` or the resolved
overload symbol). A method is keyed by its owner and its node id, never by a
free function's name, and the two key spaces must not be able to collide.
"""


def callee_frame_key(node=None, name=None):
    """The frame key for the free function `node` denotes, or None.

    `node` may be any of the shapes that name a free function:

      * a `Function` declaration (or a spliced clone of one) — `mangled_symbol`
        when registration stamped one, else the declared `name`;
      * a `FunctionCall` call site — `resolved_symbol` when call resolution
        stamped one, else the written `name`;
      * a `MethodCall` that is really a module-qualified FREE call
        (`mod.f(...)`, SL-208) — its `module_free_call`, which the typechecker
        already composed as `resolved_symbol or method_name`. A MethodCall that
        is a genuine METHOD call names no free-function frame and answers None:
        method frames are `_method_frame_key`'s, and the two spaces are
        disjoint on purpose.
      * a `FunctionSymbol` from the namespace — `mangled_name`, with the
        looked-up `name` passed alongside (a symbol carries no name of its own).

    `name` is the fallback spelling for a node that has none, and is ignored
    whenever the node carries a symbol.
    """
    if node is None:
        return name
    # A module-qualified free call wears a MethodCall's shape. `module_free_call`
    # is present exactly when the typechecker resolved it to a free function, so
    # its absence on a MethodCall means "this is a method" — answer None rather
    # than composing a free-function key out of a method name.
    if hasattr(node, 'method_name'):
        return getattr(node, 'module_free_call', None)
    symbol = (getattr(node, 'mangled_symbol', None)
              or getattr(node, 'resolved_symbol', None)
              or getattr(node, 'mangled_name', None))
    if symbol:
        return symbol
    return getattr(node, 'name', None) or name

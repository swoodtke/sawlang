"""One definition of "the children of an AST node", read side and write side.

Design 193 unit 3, from design 190's traversal-drift census. A dozen passes
hand-rolled this recursion, and the copies agreed on lists and `Argument`s but
not on TUPLES — and a tuple inside a list is exactly the shape of
`StructInit.field_inits` (`[(name, value), …]`) and `MapLiteral.entries`. So
those walks never looked inside a struct literal at all: the coroutine
transform's `if let` rename walked past `Check(detail: a)` and left the outer
binding naming a local that no longer existed (DF-187b), and the chain-assign
exclusivity check could not see `p?.f = Foo(a: move x)` (design 190's census).
One definition here, so the next node type with a tuple-shaped field cannot
reopen it.

Three entry points, and every AST walk in the compiler should be able to say
which one it is:

* `child_nodes(node)` — every AST child, for a READ-only walk.
* `map_nodes(node, rule)` — the same coverage with each node replaced in its
  parent slot, for a REWRITING walk.
* `control_blocks(stmt)` — the CONTAINER-KINDS enumeration: every `Block` a
  statement's control-flow construct owns. This one is not a tree walk but a
  single-level fan-out, for the pass-specific "spine" walks that descend
  control flow one statement at a time and must not miss a container kind.

`SawType` is not an `ASTNode`, so type annotations and type arguments stay out
of every walk here — a walk that wants types has `_type_children` in
place_uses.py. Cross-pass ANNOTATION fields stay out too (`structural_fields`
is `dataclasses.fields` minus them), so a walk can never reach a node through
a checker's back-reference and judge it twice.
"""

from ast_nodes import (
    ASTNode, Argument, BindingPattern, Block, EnumPattern, ExpressionStatement,
    ForLoop, GuardLetStatement, IfExpr, IfLetExpr, MatchExpr, TryCatchExpr,
    TryExpr, TuplePattern, WhileExpr,
    structural_fields,
)

__all__ = ["child_nodes", "map_nodes", "control_blocks", "structural_fields",
           "pattern_binding_sites", "pattern_binding_names"]


# --------------------------------------------------------------------------- #
# the read side
# --------------------------------------------------------------------------- #

def child_nodes(node):
    """Yield every AST child of `node` reachable through a structural field —
    through ANY nesting of lists and tuples, and through the `Argument` wrapper.

    Order is source order: a tuple's contents are yielded where the tuple sat.
    Anything that is not an `ASTNode` (a name string, a `SawType`, `None`)
    yields nothing, so a caller may hand this whatever it is holding.
    """
    if isinstance(node, Argument):
        yield from _expand(node.value)
        return
    if not isinstance(node, ASTNode):
        return
    for f in structural_fields(node):
        yield from _expand(getattr(node, f.name, None))


def _expand(value):
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _expand(item)
    elif isinstance(value, Argument):
        yield from _expand(value.value)
    elif isinstance(value, ASTNode):
        yield value


# --------------------------------------------------------------------------- #
# the write side
# --------------------------------------------------------------------------- #

def map_nodes(node, rule):
    """Apply `rule` to `node` and to every AST node under it, replacing each in
    its parent slot. Returns the (possibly new) root.

    The exact coverage of `child_nodes`, on the write side. LISTS are mutated in
    place — a program's declaration lists are shared between the merged ASTs, so
    rebuilding one would quietly unshare it; tuples are immutable and are
    rebuilt into their list slot.
    """
    node = rule(node)
    if isinstance(node, ASTNode):
        for f in structural_fields(node):
            value = getattr(node, f.name, None)
            new_value = _map_value(value, rule)
            if new_value is not value:
                setattr(node, f.name, new_value)
    return node


def _map_value(value, rule):
    if isinstance(value, list):
        for i, item in enumerate(value):
            value[i] = _map_value(item, rule)
        return value
    if isinstance(value, tuple):
        return tuple(_map_value(item, rule) for item in value)
    if isinstance(value, Argument):
        value.value = map_nodes(value.value, rule)
        return value
    if isinstance(value, ASTNode):
        return map_nodes(value, rule)
    return value


# --------------------------------------------------------------------------- #
# the container kinds
# --------------------------------------------------------------------------- #

# Every construct that owns a `Block` a statement can be written inside. A
# "spine" walk — one that descends control flow statement by statement, as the
# coroutine transform's hoists and the CFG walk do — has to enumerate these,
# and around twenty of them enumerated it independently. `TryCatchExpr` was the
# entry every one of them missed (DF-193a): a suspension inside a
# `try { … } catch { … }` was invisible to the hoists, and the census read the
# resulting rejection as the cause of DF-190b.
#
# A pass whose semantics differ PER CONTAINER (the coroutine CFG walk descends
# an `if let` only when it was marked `_coro_split`) still writes its own
# dispatch — this enumeration is not a straitjacket. What it removes is the
# other case: a plain descent that silently stops at a container nobody
# remembered to list.
CONTAINER_KINDS = (
    "IfExpr (then/else)", "IfLetExpr (then/else)", "WhileExpr (body)",
    "ForLoop (body)", "MatchExpr (block-bodied arms)",
    "GuardLetStatement (else)", "TryCatchExpr (try/catch)",
    "TryExpr (inline catch)",
)


def control_blocks(stmt):
    """Every `Block` the control-flow construct in `stmt` owns, in source order.

    Takes a STATEMENT (an `ExpressionStatement` is unwrapped to its expression,
    which is where `if`/`while`/`match`/`try` live) and returns a list, empty
    for a leaf statement. See `CONTAINER_KINDS` for the enumeration itself.
    """
    ctrl = stmt.expression if isinstance(stmt, ExpressionStatement) else stmt
    out = []
    if isinstance(ctrl, (IfExpr, IfLetExpr)):
        out.append(ctrl.then_branch)
        if ctrl.else_branch is not None:
            out.append(ctrl.else_branch)
    elif isinstance(ctrl, WhileExpr):
        out.append(ctrl.body)
    elif isinstance(ctrl, ForLoop):
        out.append(ctrl.body)
    elif isinstance(ctrl, MatchExpr):
        out.extend(arm.body for arm in ctrl.arms
                   if isinstance(arm.body, Block))
    elif isinstance(ctrl, GuardLetStatement):
        out.append(ctrl.else_branch)
    elif isinstance(ctrl, TryCatchExpr):
        out.append(ctrl.try_block)
        out.append(ctrl.catch_block)
    elif isinstance(ctrl, TryExpr) and ctrl.catch_block is not None:
        out.append(ctrl.catch_block)
    return [b for b in out if isinstance(b, Block)]


# The OTHER half of a container: the expression it evaluates outside every one
# of its blocks. `control_blocks` above enumerates the blocks; a walk that has
# both has seen the whole construct, and one that has only the blocks walks past
# the head in silence — which is exactly what DF-224a found (a `Channel.receive()`
# in a `match` scrutinee or an `if`/`while` condition was neither embedded into
# the coroutine frame nor refused, and spun at 100% CPU forever).
#
# SIX slots, and the pairing with `CONTAINER_KINDS` is deliberate: every
# container listed there is listed here too, either with its head or with the
# note that it has none. `TryCatchExpr` and `TryExpr` are the two with none —
# a `try { … } catch { … }` evaluates blocks and nothing else, and a `try <expr>`
# is a LEAF statement whose subject the ordinary expression walks already reach.
CONTAINER_HEADS = (
    "IfExpr (condition)", "IfLetExpr (subject)", "WhileExpr (condition)",
    "ForLoop (iterable)", "MatchExpr (scrutinee)", "GuardLetStatement (subject)",
    "TryCatchExpr (none)", "TryExpr (none — a leaf statement's subject)",
)


def control_heads(stmt):
    """Every HEAD expression the control-flow construct in `stmt` owns, as
    `(owner, field_name)` pairs so a caller can REWRITE the slot in place.

    Takes a STATEMENT, exactly as `control_blocks` does (an `ExpressionStatement`
    is unwrapped to its expression), and returns a list, empty for a leaf
    statement and for a container with no head. See `CONTAINER_HEADS`.

    A conditionless `while { … }` has no condition to return, so the list is
    empty for it — the absence is a fact about that loop, not a missing row.

    ENTRY POINTS (obligation 1 — a funnel names its entries):
      * coro_transform.py `_hoist_container_heads` — lifts a suspension-spanning
        head into a preceding driven `let`, which is what makes the head slots
        work at all.
      * coro_transform.py `_collect_calls` — the backstop: a head that STILL
        spans a suspension after that hoist is refused, never descended past.
    """
    ctrl = stmt.expression if isinstance(stmt, ExpressionStatement) else stmt
    out = []
    if isinstance(ctrl, (IfExpr, WhileExpr)):
        out.append((ctrl, 'condition'))
    elif isinstance(ctrl, (IfLetExpr, GuardLetStatement)):
        out.append((ctrl, 'optional_expr'))
    elif isinstance(ctrl, ForLoop):
        out.append((ctrl, 'iterable'))
    elif isinstance(ctrl, MatchExpr):
        out.append((ctrl, 'matched_expr'))
    return [(owner, field) for (owner, field) in out
            if getattr(owner, field, None) is not None]


# --------------------------------------------------------------------------- #
# the bindings a pattern introduces
# --------------------------------------------------------------------------- #

def pattern_binding_sites(pattern):
    """Every binding `pattern` introduces, as `(name, line, column)`, in source
    order. A wildcard, a literal and a range bind nothing.

    THE definition (design 194 unit 3). It existed three times and the copies
    had drifted in the way duplicated recursions do — over the case nobody's own
    caller reached. The typechecker's walked nested `subpatterns` generically,
    the coroutine transform's named `EnumPattern` explicitly, and codegen's
    covered `BindingPattern` and `TuplePattern` and nothing else: a `TuplePattern`
    holding an `EnumPattern` would have gone under-counted there, which for its
    callers means an `if let` shadow-restore list missing a name.

    That case is unreachable today — the typechecker refuses a variant pattern in
    both irrefutable positions ("refutable pattern in `let`/`var`", "`if let`/
    `guard let` tuple pattern must be irrefutable") before codegen sees it — so
    the gap was guarded from upstream rather than covered. One definition makes
    the guard's absence stop mattering.

    ENTRY POINTS (obligation 1 — a funnel names its entries):
      * typechecker/statements.py `_pattern_binding_names` — design-100 shadow
        checking for `let`, `if let` and `guard let` bindings.
      * codegen/statements.py `_pattern_binding_names` — the `if let`
        shadow-save/restore list and the bound-name set of a destructuring bind.
      * coro_transform.py `_pattern_binding_names` — the frame fields a
        suspension-spanning `match` arm or `if let` binding needs.
    """
    out = []
    _collect_binding_sites(pattern, out)
    return out


def _collect_binding_sites(pattern, out):
    if pattern is None:
        return
    if isinstance(pattern, BindingPattern):
        out.append((pattern.name, pattern.line, pattern.column))
        return
    if isinstance(pattern, TuplePattern):
        subs = pattern.elements
    elif isinstance(pattern, EnumPattern):
        subs = pattern.subpatterns
    else:
        # Any future composite pattern that spells its children the same way.
        # Asking structurally keeps a new node type from silently binding
        # nothing here, which is exactly how the three copies drifted.
        subs = getattr(pattern, 'subpatterns', None) or getattr(
            pattern, 'elements', None)
    for sub in subs or ():
        _collect_binding_sites(sub, out)


def pattern_binding_names(pattern):
    """`pattern_binding_sites` without the positions — for the passes that only
    need the names."""
    return [name for name, _line, _col in pattern_binding_sites(pattern)]


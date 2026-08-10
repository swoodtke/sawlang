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
    ASTNode, Argument, Block, ExpressionStatement, ForLoop, GuardLetStatement,
    IfExpr, IfLetExpr, MatchExpr, TryCatchExpr, TryExpr, WhileExpr,
    structural_fields,
)

__all__ = ["child_nodes", "map_nodes", "control_blocks", "structural_fields"]


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

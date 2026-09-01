"""THE SUBSTITUTING COPIER (design 218c Amendment A2(a)).

An instance's body is a COPY of its template with the type arguments put in.
That was two walks — `copy.deepcopy` of the whole template, then
`substitute_ast_types` over the copy — and the first one copies subtrees the
second is about to replace. This module does both in ONE pass: every node is
built already substituted, and nothing is copied twice.

It lives beside `mono_identity` on the same rationale, and the rationale is the
point rather than the address: a clone is one of the two artifacts the two
sides of this migration share (the other is the instance IDENTITY), so it has
one producer. `substitute_ast_types` survives for the caller that does NOT
copy — the post-check re-stamp in `_build_generic_struct_method_mono`, which
substitutes an already-checked clone in place — and for nothing else.

WHAT "EQUIVALENT" MEANS, precisely, because the oracle checks it (A2(a): an
equivalence assertion against deepcopy+substitute over the whole corpus, riding
one gate run):

  * every AST node is fresh and carries a FRESH `node_id`, exactly as
    `ASTNode.__deepcopy__` gives one — a clone that shared its template's ids
    would merge with it in the effect graph, in the transform's method tables
    and in the `_CatchError_<id>` union name;
  * every `SawType` is `SawType.substitute`'s answer for that type, and
    `SawType.substitute` is the authority: this module calls it rather than
    restating its eight arms, because two copies of "what substitution means"
    is the DF-190c shape;
  * the caller's own concrete types — the values of `type_map` — are SHARED,
    not copied. Substitution inserts them by reference and always has: the
    old order copied the template FIRST and substituted after, so the map's
    types were never in the copied graph at all. The memo is seeded with them
    so the copy pass cannot pull them in;
  * sharing INSIDE the clone is preserved. One memo, so a node reached twice
    is copied once and the clone has the template's aliasing rather than a
    tree where the template had a graph;
  * a symbol, an enum member, or anything else this walker does not know is
    handed to `copy.deepcopy` WITH THIS MEMO, which is what keeps the two
    answers the same object graph rather than merely the same shape.

DF-285a IS THE COPIER'S OWN RULE, and that is why the finding is named here.
A type parameter is spelled outside a type annotation in exactly one place the
language accepts — the zero-argument construction `A()` (design 37's allocator
model, which `Vector._reserve` and `Box.make` are written around) — and a
call's NAME is a `str`, so no amount of walking `SawType`s reaches it. The
rewrite belongs in the copier and never in a patch-up pass afterwards: a pass
that runs after would have to find the position again, and finding it again is
the step that was missing when the bug was filed.
"""

import copy as _copy
import dataclasses
import enum
import os

from ast_nodes import ASTNode, FunctionCall, SawType, TypeKind, _next_node_id

# SAWC_MONO_COPY_ORACLE — A2(a)'s equivalence assertion, off by default and run
# by the gate over the whole corpus for exactly as long as the old path exists.
# When set, every clone is built BOTH ways and the two are compared
# structurally; a difference is an internal error naming the field path.
_ORACLE = os.environ.get("SAWC_MONO_COPY_ORACLE", "") == "1"


def substituting_copy(node, type_map):
    """A fresh, substituted clone of `node`. The one funnel; see the module doc.

    ENTRY POINTS — every splice path (obligation 1), the same four
    `_home_module_scope` names: `_build_fn_mono`, `_splice_fn_mono`,
    `_build_method_mono`, `_build_generic_struct_method_mono`.
    """
    if _ORACLE:
        return _oracle_copy(node, type_map)
    return _substituting_copy(node, type_map)


def _substituting_copy(node, type_map):
    memo = {}
    if type_map:
        # The caller's concrete types are INSERTED by substitution, never
        # copied — see the module doc. Seeding the memo with identity entries is
        # what makes that true of the copy pass too, and it is `copy.deepcopy`'s
        # own memo protocol, so the fallback below honours it as well.
        for value in type_map.values():
            if value is not None:
                memo[id(value)] = value
    return _copy_value(node, type_map, memo)


def _copy_value(value, type_map, memo):
    if value is None:
        return None
    cls = type(value)
    # Immutable scalars are shared by `copy.deepcopy` too, and they must NOT be
    # memoized: a freed int or str can have its `id` reused under us.
    if cls in _ATOMIC:
        return value
    if isinstance(value, enum.Enum):
        # `TypeKind`, `Visibility`, `SymbolKind`. `copy.deepcopy` gives the same
        # member back (an enum member is its own singleton); saying so here is
        # what keeps the hottest field in the walk off the general path.
        return value
    hit = memo.get(id(value))
    if hit is not None:
        return hit
    if cls is SawType:
        return _copy_type(value, type_map, memo)
    if cls is list:
        out = []
        _remember(memo, value, out)
        for item in value:
            out.append(_copy_value(item, type_map, memo))
        return out
    if cls is tuple:
        out = tuple(_copy_value(item, type_map, memo) for item in value)
        _remember(memo, value, out)
        return out
    if cls is dict:
        out = {}
        _remember(memo, value, out)
        for k, v in value.items():
            out[_copy_value(k, type_map, memo)] = _copy_value(v, type_map, memo)
        return out
    if isinstance(value, ASTNode):
        return _copy_node(value, type_map, memo)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        # `Parameter`, `Argument`, `StructField`, … — AST-shaped but not nodes,
        # so they carry no `node_id` to freshen.
        return _copy_dataclass(value, type_map, memo)
    # A symbol, an enum member, a `TypeKind`, a Visibility — anything whose
    # copying rule is not this module's. Handing the SAME memo over is what
    # keeps one object graph: a symbol reached from two types is copied once,
    # exactly as it would be under a single top-level `deepcopy`.
    return _copy.deepcopy(value, memo)


def _copy_node(node, type_map, memo):
    """One AST node, substituted, with a fresh `node_id`.

    `ASTNode.__deepcopy__` walks `__dict__` and `substitute_ast_types` walks
    `dataclasses.fields()`; the design-126 AST contract (gated by the `astgraft`
    lane) is what makes those the same set, so ONE walk over `__dict__` does
    both jobs.
    """
    cls = type(node)
    new = cls.__new__(cls)
    _remember(memo, node, new)
    target = new.__dict__
    for key, value in node.__dict__.items():
        target[key] = _copy_value(value, type_map, memo)
    new.node_id = _next_node_id()
    if cls is FunctionCall:
        substitute_constructed_type_param(new, type_map)
    return new


def _copy_dataclass(obj, type_map, memo):
    cls = type(obj)
    new = cls.__new__(cls)
    _remember(memo, obj, new)
    target = new.__dict__
    for key, value in obj.__dict__.items():
        target[key] = _copy_value(value, type_map, memo)
    return new


def _copy_type(saw_type, type_map, memo):
    """One `SawType`, substituted THEN copied.

    That order, and not the other one, is what the equivalence rests on:
    `SawType.substitute` is the authority on what substitution means, and it
    returns `self` for a type its map does not touch and a freshly built node
    for one it does — whose unchanged CHILDREN are the originals. Copying its
    answer (with the map's own types memo-pinned to themselves) reaches both,
    so the clone never aliases a template type and §4's "nothing edits a
    template after capture" survives the change of order.
    """
    substituted = saw_type.substitute(type_map) if type_map else saw_type
    hit = memo.get(id(substituted))
    if hit is not None:
        # Either a map value (seeded above, shared on purpose) or a type this
        # walk already copied.
        if substituted is not saw_type:
            _remember(memo, saw_type, hit)
        return hit
    new = SawType.__new__(SawType)
    _remember(memo, saw_type, new)
    if substituted is not saw_type:
        _remember(memo, substituted, new)
    target = new.__dict__
    for key, value in substituted.__dict__.items():
        target[key] = _copy_value(value, type_map, memo)
    return new


def substitute_constructed_type_param(call, type_map):
    """`A()` in a template becomes `GlobalAllocator()` in the instance (DF-285a).

    THE POSITION MATRIX (obligation 4). A type parameter can be written outside
    a type annotation in exactly one place the language accepts: the
    zero-argument construction `A()`, checked by `_check_function_call`'s
    type-param arm, whose whole reason for existing is design 37's allocator
    model. The two neighbouring spellings were probed and are refused
    ABSTRACTLY, in the template — `M.seed()` (a static call on a parameter) is
    ``undefined variable `M` `` with no instantiation involved, and an
    enum-case spelling the same — so there is no second position for this
    mechanism to hide in.

    Rewriting the NAME (rather than teaching the instance check to accept the
    parameter's spelling) is what makes the clone an ordinary concrete program:
    `_check_function_call` then takes its struct-construction branch, stamps
    `resolved_type_identity`, and codegen lowers the instance exactly as it
    lowers a hand-written `GlobalAllocator()`.

    A construction takes no arguments (the checker refuses `A(1)` at the
    template), so the argument test keeps a same-named ordinary call — which
    the checker would have resolved to the function, function lookup coming
    first — out of the rewrite.
    """
    if not type_map or call.arguments:
        return
    bound = type_map.get(call.name)
    if bound is None:
        return
    if bound.kind == TypeKind.STRUCT:
        concrete = bound.struct_name
    elif bound.kind == TypeKind.ENUM:
        concrete = bound.enum_name
    else:
        return
    if concrete:
        call.name = concrete


# Types `copy.deepcopy` shares rather than copies, checked by exact class so a
# subclass with real state is not mistaken for one of them.
_ATOMIC = frozenset((
    type(None), bool, int, float, complex, str, bytes, type,
))


def _remember(memo, original, copied):
    """Record a copy, and keep the ORIGINAL alive for as long as the memo is.

    `copy.deepcopy`'s own convention, and it is load-bearing rather than
    tidy: the memo is keyed by `id`, and an original that is garbage collected
    mid-walk can have its address handed to a later object, which would then
    silently receive the wrong copy.
    """
    memo[id(original)] = copied
    memo.setdefault(id(memo), []).append(original)


# ---------------------------------------------------------------- the oracle
#
# A2(a) ships the copier "while shadow mode still exists" for exactly this
# reason: the old path is still there to be compared against, over the whole
# corpus, in one gate run. Two properties, because structural equality alone
# would not notice the one that matters most:
#
#   1. the two clones are structurally identical, field for field, with
#      `node_id` exempt (both fresh, and deliberately different);
#   2. the copier's clone SHARES nothing with the template except the caller's
#      own concrete types — which is §4's "nothing edits a template after
#      capture" stated as a checkable property of one clone, and is what a
#      single-pass copier could plausibly get wrong where a copy-then-rewrite
#      cannot.


def _oracle_copy(node, type_map):
    from typechecker.effects import substitute_ast_types
    mine = _substituting_copy(node, type_map)
    theirs = _copy.deepcopy(node)
    substitute_ast_types(theirs, type_map)
    where = _first_difference(mine, theirs, "clone", set())
    if where is not None:
        raise AssertionError(
            f"internal compiler error: monomorphization copier oracle: "
            f"{where}")
    shared = _template_object_shared(mine, node, type_map)
    if shared is not None:
        raise AssertionError(
            f"internal compiler error: monomorphization copier oracle: the "
            f"clone shares a template object with its template at {shared}")
    return mine


def _oracle_kind(v):
    if v is None:
        return "none"
    cls = type(v)
    if cls in _ATOMIC or isinstance(v, enum.Enum):
        return "atom"
    if cls is SawType:
        return "type"
    if cls is list:
        return "list"
    if cls is tuple:
        return "tuple"
    if cls is dict:
        return "dict"
    if isinstance(v, ASTNode) or (dataclasses.is_dataclass(v)
                                  and not isinstance(v, type)):
        return "node"
    return "opaque"


def _first_difference(a, b, path, seen):
    """The first field path at which the two clones differ, or None."""
    ka, kb = _oracle_kind(a), _oracle_kind(b)
    if ka != kb:
        return f"{path}: {ka} vs {kb} ({type(a).__name__}/{type(b).__name__})"
    if ka == "none":
        return None
    if ka == "atom":
        return None if a == b else f"{path}: {a!r} vs {b!r}"
    if ka == "opaque":
        # A symbol, or anything else neither side's walker interprets. Both
        # sides produced it with the same `copy.deepcopy`, so the CLASS is the
        # whole claim; walking a symbol would walk the namespace.
        return (None if type(a) is type(b)
                else f"{path}: {type(a).__name__} vs {type(b).__name__}")
    mark = (id(a), id(b))
    if mark in seen:
        return None
    seen.add(mark)
    if ka in ("list", "tuple"):
        if len(a) != len(b):
            return f"{path}: length {len(a)} vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            found = _first_difference(x, y, f"{path}[{i}]", seen)
            if found is not None:
                return found
        return None
    if ka == "dict":
        if set(a) != set(b):
            return f"{path}: keys {sorted(map(str, a))} vs {sorted(map(str, b))}"
        for k in a:
            found = _first_difference(a[k], b[k], f"{path}[{k!r}]", seen)
            if found is not None:
                return found
        return None
    # `type` and `node` both compare field-wise over `__dict__`.
    if type(a) is not type(b):
        return f"{path}: {type(a).__name__} vs {type(b).__name__}"
    keys = set(a.__dict__) | set(b.__dict__)
    for k in sorted(keys):
        if k == "node_id":
            continue          # fresh on both sides, by design
        if k not in a.__dict__ or k not in b.__dict__:
            return f"{path}.{k}: present on one side only"
        found = _first_difference(a.__dict__[k], b.__dict__[k],
                                  f"{path}.{k}", seen)
        if found is not None:
            return found
    return None


def _template_object_shared(clone, template, type_map):
    """A path in `clone` at which a TEMPLATE object was reused, or None."""
    allowed = set()
    for value in (type_map or {}).values():
        _collect_ids(value, allowed)
    template_ids = set()
    _collect_ids(template, template_ids)
    stack = [(clone, "clone")]
    seen = set()
    while stack:
        node, path = stack.pop()
        kind = _oracle_kind(node)
        if kind in ("none", "atom", "opaque"):
            continue
        if id(node) in seen:
            continue
        seen.add(id(node))
        # A TUPLE is exempt from the identity half and not from the walk: it is
        # immutable, so sharing one cannot edit a template, and `copy.deepcopy`
        # shares it too whenever its elements copy to themselves — `()` most of
        # all, which CPython interns.
        if (kind != "tuple" and id(node) in template_ids
                and id(node) not in allowed):
            return f"{path} ({type(node).__name__})"
        if kind in ("list", "tuple"):
            stack.extend((v, f"{path}[{i}]") for i, v in enumerate(node))
        elif kind == "dict":
            stack.extend((v, f"{path}[{k!r}]") for k, v in node.items())
        else:
            stack.extend((v, f"{path}.{k}") for k, v in node.__dict__.items())
    return None


def _collect_ids(value, out):
    stack = [value]
    while stack:
        v = stack.pop()
        kind = _oracle_kind(v)
        if kind in ("none", "atom", "opaque"):
            continue
        if id(v) in out:
            continue
        out.add(id(v))
        if kind in ("list", "tuple"):
            stack.extend(v)
        elif kind == "dict":
            stack.extend(v.values())
        else:
            stack.extend(v.__dict__.values())

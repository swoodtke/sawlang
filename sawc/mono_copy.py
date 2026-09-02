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

WHAT "EQUIVALENT" MEANS, precisely, because an oracle checked it over the whole
corpus while the old order still existed to compare against (A2(a); the switch
retired with that order at stage 3c-2c — see `substituting_copy`):

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

from ast_nodes import ASTNode, FunctionCall, SawType, TypeKind, _next_node_id


def substituting_copy(node, type_map):
    """A fresh, substituted clone of `node`. The one funnel; see the module doc.

    ENTRY POINTS — every splice path (obligation 1): the design-70/74 builders
    `_build_fn_mono`, `_build_method_mono` and `_build_generic_struct_method_mono`,
    and the monomorphization phase's own `materialize_instance`, which is the
    one that reaches every registered instance.

    THE EQUIVALENCE ORACLE IS RETIRED (design 218 unit 1.5 stage 3c-2c).
    A2(a) shipped `SAWC_MONO_COPY_ORACLE=1` — every clone built BOTH ways and
    compared structurally, plus the assertion that it shares nothing with its
    template but the caller's own types — "for exactly as long as the old path
    exists". That path is the codegen body generators, and the cutover deleted
    them: there is no second copier left to compare against, so the switch is
    gone rather than left as a lane that tests one implementation against
    itself. It ran green over the whole corpus on the gate that landed it.
    """
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

#!/usr/bin/env python3
"""Every node that can occupy a VALUE POSITION has a producer classification.

Design 269 (SL-211, unit B of the SL-209 ownership-uniformity epic). This is
the enumeration gate that turns `typechecker/producers.py` from a list somebody
maintains into a total function somebody cannot forget to extend.

WHY IT EXISTS. The producer question — "does this expression name storage an
existing owner keeps?" — used to be a hand-maintained `isinstance` tuple, and
every member anyone forgot was a soundness bug, because a node that is not on
the list answers False and EVERY tier arm of `_check_value_transfer` is gated
on that answer. Design 131, DF-299a, DF-288a, SL-218, SL-219 and SL-79 are six
instances of exactly that, filed over ten months. A list cannot be audited by
reading it; a total function can be audited by a test.

WHAT IS CHECKED:

  1. THE UNIVERSE IS COVERED. Every `Expression` subclass, plus every AST node
     declaring a `result_type` field (which is what promotes a `Statement` into
     a value position — `ForLoop` is the one such class, and it is why this
     gate does not enumerate `Expression` alone; design 267's census did, and
     missed it).
  2. THE BUCKETS ARE DISJOINT, except for the ONE documented dual membership,
     `TryExpr` — which PROJECTS its Ok value out of its subject and BRANCHES
     into its catch handler. A second overlap would be an accident and fails.
  3. THE BUCKETS HOLD ONLY REAL NODES. A stale entry for a class that no longer
     exists, or an entry that is not an AST node at all, fails.
  4. EVERY MEMBER ANSWERS. `producer_kind` returns a known kind for a bare
     instance of every classified class, so the dispatch and the table cannot
     drift apart.
  5. THE CONSUMERS GO THROUGH THE FUNNEL. `_is_aliasing_expr` and
     `_transfer_source_identity` are the two walks that must see through
     exactly the same nodes; both are checked to reference `producer_kind`, and
     `_is_aliasing_expr` is checked NOT to carry a node-type list of its own —
     which is the shape this unit removed.

Run from the repo root:  ./.venv/bin/python tools/test_producer_taxonomy.py
Exit code 0 = pass; nonzero (with a diagnostic) = fail.
"""
import ast
import dataclasses
import inspect
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "sawc"))

import ast_nodes                                              # noqa: E402
from typechecker import producers                             # noqa: E402


BUCKETS = {
    'PRODUCER_READS': producers.PRODUCER_READS,
    'PRODUCER_PROJECTS': frozenset(producers.PRODUCER_PROJECTS),
    'PRODUCER_REWRAPS': frozenset(producers.PRODUCER_REWRAPS),
    'PRODUCER_BRANCHES': producers.PRODUCER_BRANCHES,
    'PRODUCER_OWN_ARM': producers.PRODUCER_OWN_ARM,
    'PRODUCER_BUILDS': producers.PRODUCER_BUILDS,
}


def value_position_classes():
    """Every AST node class that can occupy a value position.

    Two sources, unioned, and the second is the one that matters: a
    `result_type` field is how a `Statement` becomes usable as an expression,
    so enumerating `Expression` alone under-counts the universe by exactly the
    nodes most likely to be forgotten.
    """
    found = {}
    for name, obj in vars(ast_nodes).items():
        if not inspect.isclass(obj) or obj.__module__ != ast_nodes.__name__:
            continue
        if obj is ast_nodes.Expression:
            continue
        is_expr = issubclass(obj, ast_nodes.Expression)
        has_result = (dataclasses.is_dataclass(obj)
                      and any(f.name == 'result_type'
                              for f in dataclasses.fields(obj)))
        if is_expr or has_result:
            found[obj] = name
    return found


def check_universe_covered(universe):
    problems = []
    classified = set()
    for bucket in BUCKETS.values():
        classified |= set(bucket)
    for cls, name in sorted(universe.items(), key=lambda kv: kv[1]):
        if cls not in classified:
            why = ("an `Expression` subclass"
                   if issubclass(cls, ast_nodes.Expression)
                   else "a node carrying a `result_type`, so it can sit in a "
                        "value position")
            problems.append(
                f"`{name}` has no producer classification — it is {why}. Add it "
                f"to a bucket in sawc/typechecker/producers.py; a node nothing "
                f"classifies reads as a fresh temporary and every ownership "
                f"tier goes quiet on it.")
    return problems


def check_buckets_are_disjoint():
    problems = []
    names = sorted(BUCKETS)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            overlap = set(BUCKETS[a]) & set(BUCKETS[b])
            overlap -= set(producers.PRODUCER_DUAL_KIND)
            if overlap:
                spelled = ", ".join(sorted(c.__name__ for c in overlap))
                problems.append(
                    f"{spelled} is in BOTH {a} and {b}. Exactly one class may "
                    f"be in two buckets — `TryExpr`, whose two result sources "
                    f"take two different rules — and it must be named in "
                    f"PRODUCER_DUAL_KIND with the reason written down.")
    for cls in producers.PRODUCER_DUAL_KIND:
        holders = [n for n in names if cls in BUCKETS[n]]
        if len(holders) < 2:
            problems.append(
                f"`{cls.__name__}` is declared a DUAL-KIND producer but appears "
                f"in {holders or 'no bucket'} — remove it from "
                f"PRODUCER_DUAL_KIND, or give it its second bucket.")
    return problems


def check_buckets_hold_real_nodes(universe):
    problems = []
    for name, bucket in sorted(BUCKETS.items()):
        for cls in bucket:
            if cls not in universe:
                problems.append(
                    f"{name} holds `{getattr(cls, '__name__', cls)!s}`, which is "
                    f"not a value-position AST node — a stale entry, or a class "
                    f"that was renamed.")
    return problems


def check_every_member_answers():
    """`producer_kind` answers for a bare instance of each classified class.

    The table and the dispatch are two things, and a member added to one but
    not reached by the other would be classified on paper and unclassified in
    practice.
    """
    problems = []
    for name, bucket in sorted(BUCKETS.items()):
        for cls in bucket:
            probe = cls.__new__(cls)      # no __init__: the dispatch reads only
            try:                          # the type and stamped annotations
                kind = producers.producer_kind(probe)
            except Exception as exc:      # noqa: BLE001 - the message is the point
                problems.append(f"producer_kind(`{cls.__name__}`) raised: {exc}")
                continue
            if kind not in producers.KINDS:
                problems.append(
                    f"producer_kind(`{cls.__name__}`) answered {kind!r}, which "
                    f"is not one of {producers.KINDS}")
    return problems


# ---------------------------------------------------------------------------
# 5. The consumers go through the funnel.
# ---------------------------------------------------------------------------

CONSUMERS = (
    (os.path.join(REPO, "sawc", "typechecker", "types.py"),
     "_is_aliasing_expr"),
    (os.path.join(REPO, "sawc", "typechecker", "ownership.py"),
     "_transfer_source_identity"),
)


def _function_source(path, name):
    with open(path) as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def check_consumers_use_the_funnel():
    problems = []
    for path, name in CONSUMERS:
        fn = _function_source(path, name)
        if fn is None:
            problems.append(f"{os.path.basename(path)}: `{name}` not found")
            continue
        calls = {getattr(n.func, 'attr', None) or getattr(n.func, 'id', None)
                 for n in ast.walk(fn) if isinstance(n, ast.Call)}
        if 'producer_kind' not in calls:
            problems.append(
                f"{os.path.basename(path)}: `{name}` does not call "
                f"`producer_kind`. The two transparency walks must see through "
                f"the same nodes; keeping a second list in step by hand is what "
                f"SL-218/SL-219/SL-79 were.")
    # …and the aliasing test must not have grown a node-type list of its own.
    fn = _function_source(CONSUMERS[0][0], CONSUMERS[0][1])
    if fn is not None:
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call)
                    and (getattr(node.func, 'id', None) == 'isinstance')):
                problems.append(
                    f"types.py:{node.lineno}: `_is_aliasing_expr` tests a node "
                    f"type directly. The classification belongs in "
                    f"`producers.py`, where the gate can see it.")
    return problems


def main():
    universe = value_position_classes()
    problems = []
    problems += check_universe_covered(universe)
    problems += check_buckets_are_disjoint()
    problems += check_buckets_hold_real_nodes(universe)
    problems += check_every_member_answers()
    problems += check_consumers_use_the_funnel()

    if problems:
        print("PRODUCER-TAXONOMY GATE FAILED")
        print()
        for p in problems:
            print(f"  {p}")
        print()
        print("The producer question is answered for EVERY value-position node")
        print("or it is answered for none of them: a node nothing classifies")
        print("reads as a fresh temporary, and every ownership tier arm is")
        print("gated on that answer (design 269).")
        return 1

    classified = set()
    for bucket in BUCKETS.values():
        classified |= set(bucket)
    print(f"producer-taxonomy gate: {len(universe)} value-position node classes, "
          f"{len(classified)} classified across {len(BUCKETS)} kinds, "
          f"{len(producers.PRODUCER_DUAL_KIND)} documented dual, "
          f"{len(CONSUMERS)} consumers on the funnel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

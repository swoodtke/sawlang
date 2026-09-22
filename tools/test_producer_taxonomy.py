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
  6. EVERY BRANCHING CLASS SAYS WHERE ITS ARMS ARE (SL-333, codex's p1 r4
     finding). Classifying a node as BRANCHES and knowing which blocks carry
     its arm results were TWO enumerations of one shape set, and adding
     `ScopedBlock` to the first left the transfer checkpoint blind to it while
     checks 1-5 and the `transferdecisions` gate all stayed green: check 1 says
     every node is CLASSIFIED and `transferdecisions` says every decision
     reached is RECORDED, and neither is a claim that a given arm is JUDGED.
     `PRODUCER_BRANCHES` is derived from `BRANCH_ARM_SOURCES` now, so the two
     cannot disagree — which makes this a one-line invariant, written anyway so
     that a future re-split of the table fails here instead of silently.
  7. …AND THE ARM SOURCE IS REACHED. Check 6 is structural, and a structural
     claim that a table has an entry is not a claim that the ownership
     checkpoint reads it. So `ScopedBlock`'s entry is DROPPED from the table by
     injection and the NoCopy pin is compiled: its refusal must DISAPPEAR. Run
     beside an uninjected control on the same file, because an assertion that a
     compile fails proves nothing unless the same compile passes when the
     defect is put back.

Run from the repo root:  ./.venv/bin/python tools/test_producer_taxonomy.py
Exit code 0 = pass; nonzero (with a diagnostic) = fail.
"""
import ast
import dataclasses
import inspect
import os
import subprocess
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


# ---------------------------------------------------------------------------
# 6. Every branching class says WHERE its arms are.
# ---------------------------------------------------------------------------

ARM_CONSUMER = (os.path.join(REPO, "sawc", "typechecker", "types.py"),
                "_value_branch_arm_results")


def check_branches_declare_their_arms():
    problems = []
    keys = set(producers.BRANCH_ARM_SOURCES)
    missing = producers.PRODUCER_BRANCHES - keys
    extra = keys - producers.PRODUCER_BRANCHES
    for cls in sorted(missing, key=lambda c: c.__name__):
        problems.append(
            f"`{cls.__name__}` is in PRODUCER_BRANCHES but has no entry in "
            f"BRANCH_ARM_SOURCES, so `branch_arm_sources` answers None for it "
            f"and the transfer checkpoint never visits its arms. The taxonomy "
            f"would say `judge each arm` while the consumer said `no arms`.")
    for cls in sorted(extra, key=lambda c: c.__name__):
        problems.append(
            f"`{cls.__name__}` has an arm-extraction entry but is not in "
            f"PRODUCER_BRANCHES — derive the set from the table rather than "
            f"maintaining both.")
    for cls, source in sorted(producers.BRANCH_ARM_SOURCES.items(),
                              key=lambda kv: kv[0].__name__):
        if not callable(source):
            problems.append(
                f"BRANCH_ARM_SOURCES[`{cls.__name__}`] is not callable — the "
                f"entry must be a function from the node to its arm blocks.")

    path, name = ARM_CONSUMER
    fn = _function_source(path, name)
    if fn is None:
        problems.append(f"{os.path.basename(path)}: `{name}` not found")
        return problems
    calls = {getattr(n.func, 'attr', None) or getattr(n.func, 'id', None)
             for n in ast.walk(fn) if isinstance(n, ast.Call)}
    if 'branch_arm_sources' not in calls:
        problems.append(
            f"{os.path.basename(path)}: `{name}` does not call "
            f"`branch_arm_sources`. Where a branching node's arms live is the "
            f"taxonomy's answer; a second enumeration here is what left "
            f"`ScopedBlock` unjudged (SL-333.p1 r4).")
    branch_names = {c.__name__ for c in producers.PRODUCER_BRANCHES}
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call)
                and getattr(node.func, 'id', None) == 'isinstance'):
            named = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            if named & branch_names:
                problems.append(
                    f"types.py:{node.lineno}: `{name}` tests a branch node "
                    f"type directly. That list belongs in `producers.py`, "
                    f"where check 6 can see it.")
    return problems


# ---------------------------------------------------------------------------
# 7. …and the arm source is REACHED (compile-level, injected).
# ---------------------------------------------------------------------------

SAWC_MAIN = os.path.join(REPO, "sawc", "sawc.py")
PRODUCERS_PY = os.path.join(REPO, "sawc", "typechecker", "producers.py")
NOCOPY_PIN = os.path.join(
    REPO, "examples", "errors",
    "fold_selected_tail_is_an_ownership_transfer.saw")

DROP_ENV = "SAW_TAXONOMY_DROP_ARM_SOURCE"

# Appended AFTER the derivation, so `PRODUCER_BRANCHES` still holds the class
# while `branch_arm_sources` stops answering for it — which is exactly the r4
# state: classified as BRANCHES, with no arm extraction behind it.
ARM_ANCHOR = ("PRODUCER_BRANCHES: FrozenSet[Type[Expression]] = "
              "frozenset(BRANCH_ARM_SOURCES)\n")
ARM_INJECTION = (
    "\nimport os as _taxonomy_probe_os  # injected by "
    "tools/test_producer_taxonomy.py\n"
    "if _taxonomy_probe_os.environ.get('" + DROP_ENV + "') == 'ScopedBlock':\n"
    "    BRANCH_ARM_SOURCES.pop(ScopedBlock, None)\n")

REFUSALS = ("cannot copy value of type `Owned` which implements NoCopy",
            "cannot copy value of type `Ceremony` which implements "
            "ExplicitCopy")


def _compile_pin(drop=None):
    env = dict(os.environ)
    env.pop(DROP_ENV, None)
    if drop:
        env[DROP_ENV] = drop
    out = os.path.join(REPO, ".build", "scratch", "producer_taxonomy_probe")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    run = subprocess.run([sys.executable, SAWC_MAIN, NOCOPY_PIN, "-o", out],
                         capture_output=True, text=True, cwd=REPO, env=env)
    return run.returncode, (run.stdout + run.stderr)


def check_dropped_arm_source_loses_the_refusal():
    problems = []
    if not os.path.exists(NOCOPY_PIN):
        return [f"{os.path.relpath(NOCOPY_PIN, REPO)} is gone — it is the "
                f"program this check injects against."]
    with open(PRODUCERS_PY) as fh:
        original = fh.read()
    if ARM_ANCHOR not in original:
        return [f"producers.py: the injection anchor for check 7 is gone. "
                f"Update this test rather than dropping the check — it is the "
                f"only thing that proves the arm table is READ."]

    # The control first, uninjected: the pin must refuse, or the injected run
    # below would be comparing against nothing.
    code, text = _compile_pin()
    if code == 0:
        problems.append(
            "the control compile of the NoCopy pin SUCCEEDED — the selected "
            "tail is not being judged at all, which is SL-333.p1 r4's defect.")
    for want in REFUSALS:
        if want not in text:
            problems.append(
                f"the control compile does not report `{want}`:\n{text[:800]}")
    if problems:
        return problems

    try:
        with open(PRODUCERS_PY, "w") as fh:
            fh.write(original.replace(ARM_ANCHOR,
                                      ARM_ANCHOR + ARM_INJECTION, 1))
        code, text = _compile_pin(drop="ScopedBlock")
        still = [want for want in REFUSALS if want in text]
        if still:
            problems.append(
                "dropping `ScopedBlock` from BRANCH_ARM_SOURCES left the "
                "refusal in place, so the pin does not depend on the arm "
                "table and this check proves nothing: " + "; ".join(still))
        if "Traceback (most recent call last)" in text:
            problems.append(
                "the injected compile raised a Python traceback rather than "
                "losing the refusal cleanly:\n" + text[:800])
    finally:
        with open(PRODUCERS_PY, "w") as fh:
            fh.write(original)
    return problems


def main():
    universe = value_position_classes()
    problems = []
    problems += check_universe_covered(universe)
    problems += check_buckets_are_disjoint()
    problems += check_buckets_hold_real_nodes(universe)
    problems += check_every_member_answers()
    problems += check_consumers_use_the_funnel()
    problems += check_branches_declare_their_arms()
    problems += check_dropped_arm_source_loses_the_refusal()

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
          f"{len(CONSUMERS)} consumers on the funnel, "
          f"{len(producers.BRANCH_ARM_SOURCES)} branching classes naming their "
          f"arms — and dropping one loses the pin's refusal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

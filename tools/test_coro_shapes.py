#!/usr/bin/env python3
"""design 275 U2 — THE TOTALITY GATE (`corototality`).

The promise: a suspending call EMBEDS at any nesting depth and control-flow
position, or ERRORS cleanly — it never silently blocks (designs 96/101/104).
Until this unit there was a THIRD outcome, and every instance of it reached the
corpus the same way: a walk enumerated the positions it knew about and a new
shape joined the language without joining the enumeration. `TryCatchExpr` was
DF-193a, the `match` scrutinee was DF-224a, the ANF-hoisted generic call was
SL-326, the module-qualified generic call was SL-330.

So this lane holds three lines that reading cannot:

  1. THE TABLE IS COMPLETE. `coro_shapes.CONTAINERS` names every container
     `ast_walk.CONTAINER_KINDS` names, and `coro_shapes.HEADS` every slot
     `CONTAINER_HEADS` names. Those two lists are the OTHER enumerations of the
     same fact, and comparing them is what makes a new container fail here
     rather than fall through a dispatch in silence.
  2. THE TABLE IS WELL FORMED. Every row carries one of the five dispositions;
     every REFUSE row carries a message and the issue that owns the missing
     capability, so a refusal is a pointer rather than a dead end; every SPLIT
     row names a `_split_*` routine that exists.
  3. THE TRANSFORM CONSULTS IT. `_collect_calls` calls `container_of` and
     `unclassified_container`, `_reject_buried_suspend_call` renders the table's
     messages, and both totality checks are wired into the pipeline.

AND THREE CHECKS RUN THE COMPILER RATHER THAN READING IT, because a structural
claim that a function contains a raise is not a claim that anything reaches it
(codex's SL-318.p4 r1 finding, applied to this unit before it could be made
again):

  4. an unclassified CONTAINER ICEs, naming the AST class — injected by removing
     one row from the table, restored in a `finally`;
  5. totality check (a) ICEs when a site decision is dropped — injected into
     `_record_frame_decisions`' `_emit`;
  6. totality check (b) ICEs when a plain call to a `frame_boundary` callee is
     injected into a generated resume body — the brief's own negative test, and
     the runtime-facing half: it is what proves nothing that slipped every
     static check can reach the executor as a blocking call;
  7. and it ICEs for a genuine METHOD call too, in each of the three families a
     method comes in — INSTANCE, STATIC and GENERIC-struct (frame key stamped
     by discovery). Check 6 exercises a free `FunctionCall`, and the method arm
     beside it asked only `key_of`, which answers None for a genuine method BY
     DESIGN: the ledger's method decision was never consulted, so a method left
     plain in a resume body passed (codex, SL-318.p6 r1). The node is CAPTURED
     from a real compile as the ledger classifies it and grafted back in — a
     hand-built one would test the check against something the compiler never
     produced.

Each injection is paired with an UNINJECTED control run, so none of them can
pass vacuously.
"""

import ast
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SAWC = os.path.join(REPO, "sawc")
SAWC_MAIN = os.path.join(SAWC, "sawc.py")
SHAPES = os.path.join(SAWC, "coro_shapes.py")
TRANSFORM = os.path.join(SAWC, "coro_transform.py")
LEDGER = os.path.join(SAWC, "coro_ledger.py")

sys.path.insert(0, SAWC)

import coro_shapes                                            # noqa: E402
from ast_walk import CONTAINER_KINDS, CONTAINER_HEADS         # noqa: E402

# A driven body two frames deep, with a suspending leaf — the same program the
# discovery lane's miss regression uses, for the same reason: every check below
# needs a compile that really builds frames.
PROBE = os.path.join("examples", "coro_nested_suspend_two_deep.saw")
# The frame key the totality checks are exercised against.
PROBE_KEY = "inner$m$"
# A driven body holding an `if` that spans a suspension — check 4 needs a
# CONTAINER in the program it drops the row for, which the two-deep chain has
# none of.
SHAPE_PROBE = os.path.join("examples", "coro_conditional_move_across_suspend.saw")


def _class_of(kind_string):
    """`"IfExpr (then/else)"` -> `"IfExpr"`."""
    return kind_string.split(" ", 1)[0]


def _head_owner(head_string):
    """`"IfExpr (condition)"` -> `"IfExpr"`, or None for a container the
    enumeration records as HAVING NO HEAD.

    The CLASS only, not the slot: `ast_walk.CONTAINER_HEADS` spells its slots in
    prose (`IfLetExpr (subject)`) and the table spells them as the AST FIELD
    (`optional_expr`), which is what a consumer rewrites. Comparing the prose
    would mint a third enumeration to keep in sync, and what actually has to
    hold is that every container WITH a head has a HOIST row.
    """
    name, _, rest = head_string.partition(" (")
    return None if rest.startswith("none") else name


# `ClosureExpr` is deliberately in the table and deliberately NOT in
# `CONTAINER_KINDS`: a closure body is not a statement container a spine walk
# descends, it is a body reached through a function VALUE — which is exactly why
# a suspension in one has no frame to park in (SL-316). It is a shape a
# suspension can sit in, so the table answers for it; it is not a container, so
# the spine enumeration does not name it.
TABLE_ONLY = {"ClosureExpr"}


# --------------------------------------------------------------------------- #
# 1: the table is complete against the other two enumerations
# --------------------------------------------------------------------------- #

def check_table_is_complete():
    problems = []
    classified = {row.node for row in coro_shapes.CONTAINERS.values()}
    for kind in CONTAINER_KINDS:
        cls = _class_of(kind)
        if cls not in classified:
            problems.append(
                f"`ast_walk.CONTAINER_KINDS` names `{kind}` and the shape "
                f"table classifies no disposition for `{cls}`. A container a "
                f"spine walk descends and the table does not answer for is the "
                f"gap design 275 U2 exists to close — add its row to "
                f"`sawc/coro_shapes.py` (SPLIT with its `_split_*`, or REFUSE "
                f"with a message and the issue that owns the missing split).")
    extra = classified - {_class_of(k) for k in CONTAINER_KINDS} - TABLE_ONLY
    for cls in sorted(extra):
        problems.append(
            f"the shape table classifies `{cls}`, which "
            f"`ast_walk.CONTAINER_KINDS` does not name and `TABLE_ONLY` does "
            f"not except. One of the three is stale; they are readings of one "
            f"fact.")

    head_owners = {row.node for row in coro_shapes.HEADS.values()}
    for head in CONTAINER_HEADS:
        owner = _head_owner(head)
        if owner is None:
            continue
        if owner not in head_owners:
            problems.append(
                f"`ast_walk.CONTAINER_HEADS` names `{head}` and the shape "
                f"table has no HOIST row for `{owner}`. A head is the "
                f"expression a container evaluates outside all of its blocks, "
                f"and a walk that has only the blocks walks past it in silence "
                f"— which is DF-224a (a `Channel.receive()` in a `match` "
                f"scrutinee, neither embedded nor refused, spinning at 100% "
                f"CPU).")
    return problems


# --------------------------------------------------------------------------- #
# 2: every row is well formed
# --------------------------------------------------------------------------- #

def check_rows_are_well_formed():
    problems = []
    with open(TRANSFORM) as fh:
        transform_src = fh.read()
    for row in coro_shapes.all_rows():
        where = f"{row.node}.{row.slot}"
        if row.disposition not in coro_shapes.DISPOSITIONS:
            problems.append(
                f"{where}: disposition `{row.disposition}` is not one of "
                f"{list(coro_shapes.DISPOSITIONS)}. There is no fourth "
                f"outcome, which is the whole of this unit.")
        if row.disposition == coro_shapes.REFUSE:
            if not row.reason:
                problems.append(f"{where}: a REFUSE row carries no reason.")
            if not row.issue:
                problems.append(
                    f"{where}: a REFUSE row names no issue. A shape refused "
                    f"because the split does not exist YET must point at the "
                    f"work that would build it, or the refusal is a dead end.")
        if row.disposition == coro_shapes.SPLIT:
            # A SPLIT row names the routine(s) that implement it, and for one
            # container that is a COMPOSITION: design 275 U3 gave the
            # collection `for` its split by REWRITING it into the `while let`
            # it denotes, so `_split_while` and `_split_if_let` do the work and
            # a normalization runs ahead of them. The check is the same
            # question either way — does `coro_transform.py` define what the
            # table points a reader at — asked of every routine the handler
            # names, with at least one of them a `_split_*`.
            named = re.findall(r"_[A-Za-z0-9_]+", row.handler)
            if not any(n.startswith("_split_") for n in named):
                problems.append(
                    f"{where}: a SPLIT row's handler is `{row.handler}`, which "
                    f"names no `_split_*` routine.")
            for name in named:
                if f"def {name}(" not in transform_src:
                    problems.append(
                        f"{where}: the SPLIT row names `{name}`, which "
                        f"`coro_transform.py` does not define.")
    # design 275 §3 ruling 2: the two call shapes design 44's by-value embedding
    # cannot serve are REFUSE **pending SL-322**, and the ruling's words are
    # "the refusal naming it". So each row's issue must appear in the file that
    # RAISES it, and in the pin that asserts the message — three places that
    # would otherwise drift, which is how the citation came to be missing from
    # both messages in the first place.
    pending_sources = {
        "AnyTraitDispatch": (
            os.path.join(SAWC, "typechecker", "effects.py"),
            os.path.join(REPO, "examples", "conformance",
                         "K37_existential_dispatch_suspending_impl_refused.saw")),
        "SuspendingCycle": (
            TRANSFORM,
            os.path.join(REPO, "examples", "errors",
                         "coro_suspending_recursion.saw")),
    }
    for row in coro_shapes.PENDING_SL322:
        if row.disposition != coro_shapes.REFUSE or not row.issue:
            problems.append(
                f"`{row.node}` is a pending-design row and must be REFUSE with "
                f"an issue; it is {row.disposition} / {row.issue!r}.")
            continue
        where = pending_sources.get(row.node)
        if where is None:
            problems.append(
                f"`{row.node}` is in PENDING_SL322 and this lane names no file "
                f"that raises it. Add one — a row nothing renders is a claim "
                f"about a message that may not exist.")
            continue
        raiser, pin = where
        # THE RAISER must RENDER the note from the row (`pending_note`), which
        # is stronger than naming the issue in a literal it could drift from:
        # the citation is then the row's, by construction, and changing the row
        # changes the message. THE PIN must name the issue LITERALLY, because
        # what it asserts is the rendered text a reader sees.
        for path, want, how in ((raiser, "pending_note",
                                 "render its pending note from the row "
                                 "(`coro_shapes.pending_note`), so the citation "
                                 "is the table's rather than a literal that can "
                                 "drift from it"),
                                (pin, row.issue,
                                 f"assert `{row.issue}` in the message it pins, "
                                 f"which is the text a reader sees")):
            if not os.path.exists(path):
                problems.append(f"{os.path.relpath(path, REPO)} is gone; it "
                                f"carried `{row.node}`'s {row.issue} citation.")
                continue
            with open(path) as fh:
                text = fh.read()
            if want not in text:
                problems.append(
                    f"{os.path.relpath(path, REPO)} must {how} for "
                    f"`{row.node}`, whose row says the refusal is pending "
                    f"{row.issue}. Design 275 §3 ruling 2 is that the refusal "
                    f"NAMES the design it waits on.")

    # A SPLIT row that is true of only SOME of its container's spellings
    # records the exception beside it, and the routine that raises names the
    # same issue — otherwise the table implies a split that is not there.
    classified = {row.node for row in coro_shapes.CONTAINERS.values()}
    for node, sub, issue, _how in coro_shapes.SPLIT_LIMITS:
        if node not in classified:
            problems.append(
                f"SPLIT_LIMITS names `{node}`, which the table does not "
                f"classify.")
        if issue not in transform_src:
            problems.append(
                f"SPLIT_LIMITS says `{node}` refuses {sub} pending {issue}, "
                f"and `coro_transform.py` names no `{issue}` — the refusal it "
                f"raises must point at the work that would build the split, or "
                f"the message is a dead end.")
    return problems


# --------------------------------------------------------------------------- #
# 3: the transform consults the table
# --------------------------------------------------------------------------- #

# (the function that must contain it, the call, why)
CONSULTATIONS = [
    ("_collect_calls", "coro_shapes.unclassified_container",
     "the invariant: a container that owns a block and has no row must ICE, "
     "never fall through to an in-place lowering"),
    ("_collect_calls", "coro_shapes.container_of",
     "the dispatch itself — the hand-written `isinstance` chain it replaced is "
     "how DF-193a's `TryCatchExpr` came to be skipped"),
    ("_suspend_in_closure_message", "coro_shapes.refusal_of",
     "the ClosureExpr REFUSE row's message"),
    ("_reject_buried_suspend_call", "coro_shapes.unbuildable_message",
     "SL-287's refusal, out of the ledger's recorded reason"),
    ("_record_frame_decisions", "coro_shapes.unclassified_container",
     "totality check (a)'s shape half, which is what makes a NEW AST shape "
     "fail coverage until the table classifies it"),
    ("transform_program", "_verify_resume_totality",
     "totality check (b), the runtime-facing half"),
    ("_verify_resume_totality", "ledger.method_target",
     "the METHOD arm of totality check (b). `key_of` answers None for a "
     "genuine method BY DESIGN, so a check that asks only that one sees free "
     "and module-qualified calls and nothing else — which is how an instance "
     "or static method left plain in a resume body passed it (codex, "
     "SL-318.p6 r1)"),
    ("transform_program", "_refuse_undriven_suspending_closures",
     "SL-316: a closure body that really suspends is refused wherever written"),
]


def _toplevel_functions(tree):
    out = {}

    def walk(node, owner):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = owner or child.name
                out.setdefault(name, []).append(child)
                walk(child, name)
            elif isinstance(child, ast.ClassDef):
                walk(child, owner)
            else:
                walk(child, owner)

    walk(tree, None)
    return out


def check_transform_consults_the_table():
    with open(TRANSFORM) as fh:
        src = fh.read()
    tree = ast.parse(src)
    funcs = _toplevel_functions(tree)
    lines = src.splitlines()
    problems = []
    for owner, call, why in CONSULTATIONS:
        nodes = funcs.get(owner)
        if not nodes:
            problems.append(
                f"`{owner}` is gone from coro_transform.py; it was the "
                f"consumer of `{call}` ({why}).")
            continue
        body = "\n".join(
            "\n".join(lines[n.lineno - 1:(n.end_lineno or n.lineno)])
            for n in nodes)
        if call not in body:
            problems.append(
                f"`{owner}` no longer calls `{call}` — {why}. The shape table "
                f"is a funnel only while its consumers read it.")
    return problems


# --------------------------------------------------------------------------- #
# the injection harness
# --------------------------------------------------------------------------- #

PROBE_ENV_KEYS = ("SAW_SHAPES_DROP_CLASS", "SAW_TOTALITY_DROP_SITE",
                  "SAW_TOTALITY_INJECT_CALL", "SAW_TOTALITY_CAPTURE_METHOD",
                  "SAW_TOTALITY_INJECT_METHOD")


def _run_probe(env_extra=None, program=None):
    env = dict(os.environ)
    env.pop("SAW_DEBUG", None)
    for key in PROBE_ENV_KEYS:
        env.pop(key, None)
    env.update(env_extra or {})
    out = os.path.join(REPO, ".build", "scratch", "coro_shapes_probe")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    return subprocess.run(
        [sys.executable, SAWC_MAIN, program or PROBE, "-o", out],
        capture_output=True, text=True, cwd=REPO, env=env)


def _injected(patches, runs, what, program=None):
    """Patch every (path, anchor, injection) in `patches`, run `runs`, restore.

    `runs` is a list of (env, expected_substrings, description); an empty
    expectation means the compile must SUCCEED. Several patches, because the
    method-family controls need TWO: one that CAPTURES a real typed node while
    the transform classifies it, and one that grafts that node back into a
    generated resume body. Synthesizing a `MethodCall` here instead would test
    the check against a node the compiler never produced, which is the one
    thing a negative control may not do.
    """
    originals = {}
    problems = []
    for path, anchor, _injection in patches:
        with open(path) as fh:
            originals[path] = fh.read()
        if anchor not in originals[path]:
            problems.append(
                f"{os.path.relpath(path, REPO)}: the injection anchor for "
                f"{what} is gone. Update this test rather than dropping the "
                f"check — it is the only thing that proves the invariant is "
                f"REACHED rather than merely present.")
    if problems:
        return problems
    try:
        for path, anchor, injection in patches:
            with open(path, "w") as fh:
                fh.write(originals[path].replace(anchor, anchor + injection, 1))
        for env, expected, desc in runs:
            run = _run_probe(env, program)
            text = (run.stdout + run.stderr).strip()
            if not expected:
                if run.returncode != 0:
                    problems.append(
                        f"{desc}: the injection itself broke the compile "
                        f"(exit {run.returncode}), so the regression beside it "
                        f"proves nothing:\n{text[:600]}")
                continue
            if run.returncode == 0:
                problems.append(
                    f"{desc}: the compile SUCCEEDED. {what} did not fire, so "
                    f"the third outcome is reachable again.")
                continue
            for want in expected:
                if want not in text:
                    problems.append(
                        f"{desc}: the report does not contain `{want}`:\n"
                        f"{text[:800]}")
            if "Traceback (most recent call last)" in text:
                problems.append(
                    f"{desc}: a raw Python traceback reached the user; an "
                    f"invariant failure goes through `_report_ice`.")
    finally:
        for path, text in originals.items():
            with open(path, "w") as fh:
                fh.write(text)
    return problems


# --------------------------------------------------------------------------- #
# 4: an unclassified container ICEs, naming the class
# --------------------------------------------------------------------------- #

SHAPE_ANCHOR = "def unclassified_container(ctrl, owns_blocks):\n"
SHAPE_INJECTION = (
    "    import os as _saw_probe_os\n"
    "    if (type(ctrl).__name__\n"
    "            == _saw_probe_os.environ.get('SAW_SHAPES_DROP_CLASS')):\n"
    "        raise UnclassifiedShape(\n"
    "            'the coroutine shape table classifies no disposition for '\n"
    "            '`' + type(ctrl).__name__ + '`, which owns a block a '\n"
    "            'suspension was found in (injected)')\n")


def check_unclassified_container_ices():
    return _injected(
        [(SHAPES, SHAPE_ANCHOR, SHAPE_INJECTION)],
        [({}, (), "the control compile with nothing dropped"),
         ({"SAW_SHAPES_DROP_CLASS": "IfExpr"},
          ("internal compiler error", "IfExpr"),
          "dropping `IfExpr` from the shape table")],
        "the unclassified-shape invariant", program=SHAPE_PROBE)


# --------------------------------------------------------------------------- #
# 5: totality check (a) ICEs when a site decision is dropped
# --------------------------------------------------------------------------- #

SITE_ANCHOR = "    def _emit(node, callee, context, outcome, src):\n"
SITE_INJECTION = (
    "        import os as _saw_probe_os\n"
    "        if callee == _saw_probe_os.environ.get('SAW_TOTALITY_DROP_SITE'):\n"
    "            return\n")


def check_dropped_site_ices():
    return _injected(
        [(TRANSFORM, SITE_ANCHOR, SITE_INJECTION)],
        [({}, (), "the control compile with nothing dropped"),
         ({"SAW_TOTALITY_DROP_SITE": PROBE_KEY},
          ("internal compiler error", "no site decision covers"),
          f"dropping the site decision for `{PROBE_KEY}`")],
        "totality check (a)")


# --------------------------------------------------------------------------- #
# 6: totality check (b) ICEs on a plain call injected into a resume body
# --------------------------------------------------------------------------- #
#
# THE BRIEF'S OWN NEGATIVE TEST. A `FunctionCall` naming a `frame_boundary`
# callee is grafted into the first generated resume body, which is exactly the
# shape the transform used to EMIT when it declined an edge: the park then
# reached codegen's out-of-frame fallback and stopped the cooperative executor's
# own OS thread.

RESUME_ANCHOR = "def _verify_resume_totality(resume_extensions, ledger):\n"
RESUME_INJECTION = (
    '    """(injected by tools/test_coro_shapes.py)"""\n'
    "    import os as _saw_probe_os\n"
    "    _saw_probe_key = _saw_probe_os.environ.get('SAW_TOTALITY_INJECT_CALL')\n"
    "    if _saw_probe_key:\n"
    "        for _ext in resume_extensions:\n"
    "            for _m in getattr(_ext, 'methods', None) or ():\n"
    "                _b = getattr(_m, 'body', None)\n"
    "                if _b is None or not getattr(_b, 'statements', None):\n"
    "                    continue\n"
    "                _b.statements.insert(0, ExpressionStatement(\n"
    "                    expression=FunctionCall(\n"
    "                        name=_saw_probe_key, arguments=[])))\n"
    "                break\n"
    "            else:\n"
    "                continue\n"
    "            break\n")


def check_injected_plain_call_ices():
    return _injected(
        [(TRANSFORM, RESUME_ANCHOR, RESUME_INJECTION)],
        [({}, (), "the control compile with nothing injected"),
         ({"SAW_TOTALITY_INJECT_CALL": PROBE_KEY},
          ("internal compiler error", "PLAIN CALL", PROBE_KEY, "__Frame_"),
          f"injecting a plain call to `{PROBE_KEY}` into a resume body")],
        "totality check (b)")


# --------------------------------------------------------------------------- #
# 7: totality check (b) ICEs on a plain METHOD call injected into a resume body
# --------------------------------------------------------------------------- #
#
# THE FAMILY CHECK 6 DOES NOT REACH (codex, SL-318.p6 r1 P1b). Check 6 injects a
# `FunctionCall`, and the method loop beside it asked `key_of` — which answers
# None for a genuine method BY DESIGN — plus `is_chan_recv`, and nothing else.
# So the ledger's own method decision was never consulted and an instance or
# static method left as a plain call in a resume body was invisible to the check
# that exists to catch it. Codex proved that by injecting the REAL TYPED
# `c.step()` node: the frozen ledger answered
# `MethodTarget(kind='embed', frame_key='Counter_step')` and the check returned
# successfully.
#
# So do the same, for each of the three families a method call comes in — an
# INSTANCE method, a STATIC method, and a GENERIC-struct method whose frame key
# discovery STAMPED on the call. The node is CAPTURED from a real compile at the
# moment the ledger classifies it (a second injection, into `method_target`) and
# grafted back into a generated resume body; a hand-built `MethodCall` would
# test the check against a node the compiler never produced.

CAPTURE_ANCHOR = "    def method_target(self, mc):\n"
CAPTURE_INJECTION = (
    "        import os as _saw_probe_os\n"
    "        _saw_probe_want = _saw_probe_os.environ.get(\n"
    "            'SAW_TOTALITY_CAPTURE_METHOD')\n"
    "        if (_saw_probe_want\n"
    "                and getattr(mc, 'method_name', None) == _saw_probe_want):\n"
    "            globals().setdefault('_saw_probe_captured', []).append(mc)\n")

METHOD_INJECTION = (
    '    """(injected by tools/test_coro_shapes.py)"""\n'
    "    import os as _saw_probe_os\n"
    "    if _saw_probe_os.environ.get('SAW_TOTALITY_INJECT_METHOD'):\n"
    "        _saw_probe_nodes = getattr(\n"
    "            coro_ledger, '_saw_probe_captured', None)\n"
    "        if not _saw_probe_nodes:\n"
    "            raise coro_ledger.LedgerMiss(\n"
    "                'the coro-totality probe captured no method call, so it "
    "had nothing to inject')\n"
    "        for _ext in resume_extensions:\n"
    "            for _m in getattr(_ext, 'methods', None) or ():\n"
    "                _b = getattr(_m, 'body', None)\n"
    "                if _b is None or not getattr(_b, 'statements', None):\n"
    "                    continue\n"
    "                _b.statements.insert(0, ExpressionStatement(\n"
    "                    expression=_saw_probe_nodes[0]))\n"
    "                break\n"
    "            else:\n"
    "                continue\n"
    "            break\n")

# (family, program, method name, the substrings the ICE must carry)
METHOD_FAMILIES = [
    ("an INSTANCE method",
     os.path.join("examples", "coro_nested_suspend_method.saw"),
     "step", ("Counter.step", "Counter_step")),
    ("a STATIC method",
     os.path.join("examples", "coro_static_method_suspends.saw"),
     "doubling", ("Napper.doubling",)),
    ("a GENERIC-struct method (its frame key STAMPED by discovery)",
     os.path.join("examples", "conformance",
                  "K34_suspending_generic_struct_method_embedded.saw"),
     "describe", ("Box2.describe",)),
]


def check_injected_plain_method_call_ices():
    problems = []
    for family, program, method, wanted in METHOD_FAMILIES:
        problems += _injected(
            [(LEDGER, CAPTURE_ANCHOR, CAPTURE_INJECTION),
             (TRANSFORM, RESUME_ANCHOR, METHOD_INJECTION)],
            [({"SAW_TOTALITY_CAPTURE_METHOD": method}, (),
              f"{family}: the control compile, capturing `{method}` and "
              f"injecting nothing"),
             ({"SAW_TOTALITY_CAPTURE_METHOD": method,
               "SAW_TOTALITY_INJECT_METHOD": "1"},
              ("internal compiler error", "PLAIN CALL", "__Frame_") + wanted,
              f"{family}: injecting the real typed `{method}` call into a "
              f"resume body")],
            "totality check (b)'s method arm", program=program)
    return problems


def main():
    problems = []
    problems += check_table_is_complete()
    problems += check_rows_are_well_formed()
    problems += check_transform_consults_the_table()
    problems += check_unclassified_container_ices()
    problems += check_dropped_site_ices()
    problems += check_injected_plain_call_ices()
    problems += check_injected_plain_method_call_ices()

    if problems:
        print("CORO-TOTALITY GATE FAILED")
        print()
        for p in problems:
            print(f"  {p}")
        print()
        print("A suspending call EMBEDS or ERRORS; it never silently blocks")
        print("(designs 96/101/104, made total by design 275 U2). Every shape")
        print("a suspension can sit in is SPLIT, HOIST, INLINE, EMBED or")
        print("REFUSE — `sawc/coro_shapes.py` is the one table that says which.")
        return 1

    rows = coro_shapes.all_rows()
    print(f"coro-totality gate: {len(rows)} shape rows over "
          f"{len(CONTAINER_KINDS)} containers and "
          f"{len([h for h in CONTAINER_HEADS if _head_owner(h)])} heads, "
          f"{len(CONSULTATIONS)} consumers reading the table, an unclassified "
          f"container ICEs naming the class, a dropped site decision ICEs, "
          f"an injected plain call to `{PROBE_KEY}` in a resume body ICEs "
          f"naming the frame, and so does a real typed method call from each "
          f"of {len(METHOD_FAMILIES)} families.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

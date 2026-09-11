#!/usr/bin/env python3
"""Every ownership boundary the checkpoint reaches carries an EXPLICIT decision.

Design 267 step 3 (SL-210, unit A of the SL-209 ownership-uniformity epic).
This is that unit's acceptance oracle, and it exists because the property it
checks is invisible from the outside: a program compiles identically whether
the checkpoint decided "nothing owed" or was never reached at all, which was
precisely the defect — `needs_copy` false and `needs_copy` never asked looked
the same.

WHAT IS CHECKED, over a fixture corpus that names one boundary per program:

  1. THE FUNNEL IS THE ONLY WRITER. Every `return` in `_check_value_transfer`
     goes through `_decide_transfer`, checked by reading the source: a bare
     `return` in that function would be a boundary with no record. This is a
     STATIC check and it is the one that keeps the property true as the
     function grows.
  2. EVERY DECISION IS WELL-FORMED. The action is one of the eight, the
     cleanup is one of the four, and the action/cleanup pair is one the model
     admits (a `copy` never retires its source, a `move` always does).
  3. THE BOUNDARY MATRIX IS COVERED. Each fixture asserts the decisions its
     one boundary produces — the destination context, the action, and the
     source KIND — so a refactor that quietly stops checking a position (or
     starts answering it differently) fails here rather than at a double free
     three units later.
  4. TRIVIAL COPIES ARE RECORDED. The acceptance criterion says "including
     trivial copies", so one fixture is a POD read whose decision used to be a
     silent fall-off-the-end.

Run from the repo root:  ./.venv/bin/python tools/test_transfer_decisions.py
Exit code 0 = pass; nonzero (with a diagnostic) = fail.
"""
import ast
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "sawc"))

import sawc as sawc_mod                                        # noqa: E402
from typechecker import ownership                              # noqa: E402


# ---------------------------------------------------------------------------
# 1. The funnel is the only writer.
# ---------------------------------------------------------------------------

TYPES_PY = os.path.join(REPO, "sawc", "typechecker", "types.py")
CHECKPOINT = "_check_value_transfer"


#: The checkpoint's LOCAL recorder (design 269). Every arm returns through it
#: so that none can forget the sub-decisions a node with a second result source
#: has already filed — a `try`'s catch handler, judged ahead of the `try`'s own
#: Ok projection. It is an accepted `return` target only because this gate also
#: proves it routes to `_decide_transfer` and to nothing else.
LOCAL_RECORDER = "decide"


def check_every_exit_records():
    """Every `return` in the checkpoint returns a recorded decision.

    A bare `return`, or a `return` of anything that is not a
    `_decide_transfer(...)` call, the local `decide(...)` recorder, or a
    recursive `_check_value_transfer(...)`, is a boundary the ledger will not
    carry — which is the exact defect design 267 removed, reintroduced. Reading
    the AST rather than trusting a comment is what makes the rule survive the
    next edit.

    The local recorder is checked too, and on the same terms: it must exist,
    must live inside the checkpoint, and must itself return a
    `_decide_transfer(...)` call. Otherwise accepting it here would be a hole
    the size of the property.
    """
    with open(TYPES_PY) as f:
        tree = ast.parse(f.read())
    target = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == CHECKPOINT:
            target = node
            break
    if target is None:
        return [f"{CHECKPOINT} not found in sawc/typechecker/types.py"]

    problems = []

    # The local recorder must be one, before any arm is allowed to use it.
    recorder = None
    for node in target.body:
        if isinstance(node, ast.FunctionDef) and node.name == LOCAL_RECORDER:
            recorder = node
            break
    if recorder is None:
        problems.append(
            f"types.py:{target.lineno}: {CHECKPOINT} has no local "
            f"`{LOCAL_RECORDER}` helper, but the arms return through one")
    else:
        writes = [n for n in ast.walk(recorder) if isinstance(n, ast.Return)]
        if not writes:
            problems.append(
                f"types.py:{recorder.lineno}: `{LOCAL_RECORDER}` records "
                f"nothing")
        for w in writes:
            fn = getattr(w.value, 'func', None)
            name = (getattr(fn, 'attr', None) or getattr(fn, 'id', None)) \
                if fn is not None else None
            if name != '_decide_transfer':
                problems.append(
                    f"types.py:{w.lineno}: `{LOCAL_RECORDER}` returns "
                    f"`{name}(...)`; it is accepted as an exit only because it "
                    f"files through `_decide_transfer`")

    for node in ast.walk(target):
        if not isinstance(node, ast.Return):
            continue
        if recorder is not None and node in ast.walk(recorder):
            continue                      # already judged, above
        value = node.value
        if value is None:
            problems.append(
                f"types.py:{node.lineno}: a bare `return` in {CHECKPOINT} — "
                f"this boundary would carry no decision")
            continue
        if not isinstance(value, ast.Call):
            problems.append(
                f"types.py:{node.lineno}: {CHECKPOINT} returns "
                f"`{ast.unparse(value)[:48]}`, which is not a recorded decision")
            continue
        name = getattr(value.func, 'attr', None) or getattr(value.func, 'id', None)
        if name not in ('_decide_transfer', LOCAL_RECORDER, CHECKPOINT):
            problems.append(
                f"types.py:{node.lineno}: {CHECKPOINT} returns `{name}(...)`; "
                f"only `_decide_transfer` and the local `{LOCAL_RECORDER}` "
                f"record a decision")
    # A function that can fall off its end has an unrecorded exit too.
    last = target.body[-1]
    if not isinstance(last, ast.Return):
        problems.append(
            f"types.py:{target.lineno}: {CHECKPOINT} can fall off its end, "
            f"which is an exit that records no decision")
    return problems


# ---------------------------------------------------------------------------
# 2. Well-formedness of the model.
# ---------------------------------------------------------------------------

# The cleanup a given action may require. Read it as the ownership model in one
# table: an action that duplicates leaves the source's obligation alone and
# mints a second, an action that transfers retires or adopts one, and an action
# that judges nothing changes no obligation at all.
LEGAL_CLEANUP = {
    ownership.ACTION_TAKE: {ownership.CLEANUP_ADOPT_TEMPORARY},
    ownership.ACTION_COPY: {ownership.CLEANUP_RETAIN_SOURCE,
                            ownership.CLEANUP_NONE},
    ownership.ACTION_MOVE: {ownership.CLEANUP_RETIRE_SOURCE},
    ownership.ACTION_NONE: {ownership.CLEANUP_NONE},
    ownership.ACTION_BORROW: {ownership.CLEANUP_NONE},
    ownership.ACTION_REFUSED: {ownership.CLEANUP_NONE},
    ownership.ACTION_DELEGATED: {ownership.CLEANUP_NONE},
    ownership.ACTION_DEFERRED: {ownership.CLEANUP_NONE},
}


def check_well_formed(decisions):
    problems = []
    for d in decisions:
        if d.action not in ownership.ACTIONS:
            problems.append(f"unknown action `{d.action}` at {d.site}")
            continue
        if d.cleanup not in LEGAL_CLEANUP[d.action]:
            problems.append(
                f"action `{d.action}` with cleanup `{d.cleanup}` at {d.site} — "
                f"the model admits {sorted(LEGAL_CLEANUP[d.action])}")
        if d.action == ownership.ACTION_DELEGATED and d.delegates:
            for key in d.delegates:
                if key is None:
                    problems.append(f"delegated decision at {d.site} names a "
                                    f"missing sub-decision")
    return problems


# ---------------------------------------------------------------------------
# 3 + 4. The boundary matrix, one fixture per row.
#
# Each fixture is (name, source, expectations, checks). An expectation is
# (destination context, action, source kind) and every one of them must appear
# among the decisions the ENTRY file produced; contexts are the checkpoint's
# own `context` strings, which is what makes a fixture readable against the
# entry-point list in its docstring. `checks` is a list of callables taking
# the decision list and returning an error string or None — that is where the
# assertions about the SOURCE IDENTITY live, because those are relationships
# between decisions rather than properties of one.
#
# WHY IDENTITY IS ASSERTED AS A RELATIONSHIP. `binding_id` comes from a global
# counter, and the front half runs more than once over one AST, so the absolute
# numbers differ between passes and between runs. What is stable — and what the
# SL-210 review found broken — is which decisions AGREE: a shadowed arm's tail
# must not carry its shadower's id, a `move` that retires a source must name
# one. Asserting the numbers would be asserting the counter.
# ---------------------------------------------------------------------------


def _at(decisions, line, column=None):
    """Every decision recorded at one source position."""
    return [d for d in decisions
            if d.site[1] == line and (column is None or d.site[2] == column)]


def _ids(decisions):
    return {d.source.binding_id for d in decisions}


def shadowed_arms_name_different_bindings(decisions):
    """The review's headline: an inner `x` and the outer `x` it shadows are two
    sources, and the branch tail must be recorded under the one the author
    wrote — not the one that happens to be visible once the arm's scope pops."""
    inner = _at(decisions, 8, 9)      # the then-arm's tail `x` (inner binding)
    outer = _at(decisions, 9, 14)     # the else-arm's `x` (outer binding)
    if not inner or not outer:
        return (f"expected a decision at 8:9 and one at 9:14; got "
                f"{len(inner)} and {len(outer)}")
    inner_ids, outer_ids = _ids(inner), _ids(outer)
    if None in inner_ids or None in outer_ids:
        return f"a shadowed arm has no identity: {inner_ids} / {outer_ids}"
    if inner_ids & outer_ids:
        return (f"the shadowed arm tail resolved to its SHADOWER: "
                f"{inner_ids} overlaps {outer_ids}")
    # …and the arm tail must name the SAME binding the `let z = x` above it did.
    let_z = _ids(_at(decisions, 6, 9))
    if let_z != inner_ids:
        return (f"the arm tail names {inner_ids} but the `let z = x` in the "
                f"same scope names {let_z}")
    return None


def tail_names_its_binding(decisions):
    """A body's TAIL is checked after its scope pops, which is where the id
    used to go missing."""
    tails = [d for d in decisions
             if d.destination.startswith("function `")
             and d.source.kind in ("binding", "projection")]
    if not tails:
        return "expected a tail decision reading a local binding"
    missing = [d for d in tails if d.source.binding_id is None]
    if missing:
        return (f"{len(missing)} tail decision(s) name no binding: "
                f"{[d.source.display for d in missing]}")
    return None


def retire_names_its_source(decisions):
    """A `move` retires exactly one binding, so a `retire-source` with no
    identity is the one shape a consumer cannot act on at all."""
    moves = [d for d in decisions if d.action == ownership.ACTION_MOVE]
    if not moves:
        return "expected a `move` decision"
    anonymous = [d for d in moves if d.source.binding_id is None]
    if anonymous:
        return (f"{len(anonymous)} `move` decision(s) retire an unidentified "
                f"source: {[(d.destination, d.source.display) for d in anonymous]}")
    return None


def diverging_source_acquires_nothing(decisions):
    """Action AND cleanup together — a `none` action with an adopt cleanup
    would still be recording an acquisition."""
    never = [d for d in decisions
             if d.source_type is not None and str(d.source_type) == "Never"]
    if not never:
        return "expected a decision whose source type is `Never`"
    wrong = [d for d in never
             if d.action != ownership.ACTION_NONE
             or d.cleanup != ownership.CLEANUP_NONE]
    if wrong:
        return (f"a diverging source recorded an acquisition: "
                f"{[(d.action, d.cleanup) for d in wrong]}")
    return None


def projection_root_is_identified(decisions):
    """The obligation-4 sibling: a PROJECTION in an arm tail is rooted at a
    binding whose scope has also popped, and its root must still be named."""
    projections = [d for d in decisions if d.source.kind == "projection"]
    if not projections:
        return "expected a projection decision"
    missing = [d for d in projections if d.source.binding_id is None]
    if missing:
        return (f"{len(missing)} projection(s) name no root binding: "
                f"{[d.source.display for d in missing]}")
    return None

_RES = """struct Res { w: Int }
extension Res: NoCopy {}
"""

FIXTURES = [
    (
        "binding_take_temporary",
        _RES + """
func main() {
    let a = Res(w: 1)
    print(a.w)
}
""",
        [("let binding", ownership.ACTION_TAKE, ownership.SOURCE_TEMPORARY)],
    ),
    (
        "binding_move_retires_source",
        _RES + """
func main() {
    let a = Res(w: 1)
    let b = move a
    print(b.w)
}
""",
        [("let binding", ownership.ACTION_MOVE, ownership.SOURCE_BINDING)],
    ),
    (
        "trivial_copy_is_recorded",
        """
func main() {
    let a = 7
    let b = a
    print(b)
}
""",
        [("let binding", ownership.ACTION_COPY, ownership.SOURCE_BINDING)],
    ),
    (
        "copy_tier_retains_source",
        """
func main() {
    let a = "text"
    let b = a
    print(b)
}
""",
        [("let binding", ownership.ACTION_COPY, ownership.SOURCE_BINDING)],
    ),
    (
        "argument_and_borrow",
        _RES + """
func sink(r: Res) -> Int { r.w }
func peek(r: &Res) -> Int { r.w }

func main() {
    let a = Res(w: 1)
    print(peek(&a))
    print(sink(move a))
}
""",
        [("call argument", ownership.ACTION_BORROW, ownership.SOURCE_REFERENCE),
         ("call argument", ownership.ACTION_MOVE, ownership.SOURCE_BINDING)],
    ),
    (
        "aggregate_elements",
        """
struct Pair { a: Int, b: Int }

func main() {
    let n = 3
    let p = Pair(a: n, b: 4)
    let t = (n, 5)
    let v: Vector<Int> = [n, 6]
    print(p.a + t.0 + v.len())
}
""",
        [("struct field", ownership.ACTION_COPY, ownership.SOURCE_BINDING),
         ("tuple element", ownership.ACTION_COPY, ownership.SOURCE_BINDING),
         ("array element", ownership.ACTION_COPY, ownership.SOURCE_BINDING)],
    ),
    (
        "value_branch_delegates_per_arm",
        _RES + """
func choose(flag: Bool) -> Int {
    let a = Res(w: 7)
    let b = if flag { move a } else { Res(w: 1) }
    b.w
}

func main() { print(choose(true)) }
""",
        [("let binding", ownership.ACTION_DELEGATED, ownership.SOURCE_TEMPORARY),
         ("let binding", ownership.ACTION_MOVE, ownership.SOURCE_BINDING)],
    ),
    (
        "refusal_is_recorded",
        _RES + """
func sink(r: Res) -> Int { r.w }

func main() {
    let a = Res(w: 1)
    print(sink(a))
}
""",
        [("call argument", ownership.ACTION_REFUSED, ownership.SOURCE_BINDING)],
    ),
    (
        "generic_body_defers_to_specialization",
        """
func hold<T>(x: T) -> Int { let a = x  1 }

func main() { print(hold(5)) }
""",
        [("let binding", ownership.ACTION_DEFERRED, ownership.SOURCE_BINDING)],
    ),
    (
        "closure_capture_and_tail",
        """
func run(body: () sync -> Int) -> Int { body() }

func main() {
    let tag = "abc"
    print(run({ [tag] in tag.len() }))
}
""",
        # A PLAIN capture is the one that reaches the checkpoint; the `move` and
        # `copy` capture modes are answered before it, which is a row of the
        # inventory's capture boundary rather than an omission here.
        [("closure capture", ownership.ACTION_COPY, ownership.SOURCE_BINDING)],
    ),
    # ---- SL-210 review: the SOURCE IDENTITY rows. -------------------------
    (
        # The reviewer's exact program. Line numbers are load-bearing (the
        # checks read 6:9, 8:9 and 9:14), so do not reflow this body.
        "shadowed_branch_arm_keeps_its_own_binding",
        """
func choose(flag: Bool) -> Int {
    let x = 7
    let y = if flag {
        let x = x + 1
        let z = x
        print(z)
        x
    } else { x }
    y
}
func main() { print(choose(true)) }
""",
        [("let binding", ownership.ACTION_COPY, ownership.SOURCE_BINDING)],
        [shadowed_arms_name_different_bindings, tail_names_its_binding],
    ),
    (
        "move_tail_retire_names_its_source",
        _RES + """
func make() -> Res {
    let r = Res(w: 1)
    move r
}
func main() { print(make().w) }
""",
        [("function `make`", ownership.ACTION_MOVE, ownership.SOURCE_BINDING)],
        [retire_names_its_source],
    ),
    (
        "diverging_initializer_is_no_value",
        """
func main() {
    let x: Int = panic("stop")
    print(x)
}
""",
        [("let binding", ownership.ACTION_NONE, ownership.SOURCE_TEMPORARY)],
        [diverging_source_acquires_nothing],
    ),
    (
        "projection_tail_names_its_root",
        """
struct Holder { tag: String }

func pick(flag: Bool) -> String {
    let h = Holder(tag: "a")
    if flag { h.tag } else { h.tag }
}
func main() { print(pick(true)) }
""",
        [("function `pick`", ownership.ACTION_COPY, ownership.SOURCE_PROJECTION)],
        [projection_root_is_identified, tail_names_its_binding],
    ),
]


def compile_and_collect(source, workdir, name):
    """Compile `source` and return every decision made for its OWN file."""
    path = os.path.join(workdir, f"{name}.saw")
    with open(path, "w") as f:
        f.write(source)
    captured = []
    base = sawc_mod.TypeChecker

    class Spy(base):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            captured.append(self)

    sawc_mod.TypeChecker = Spy
    try:
        try:
            sawc_mod.compile_saw(path, os.path.join(workdir, name),
                                 optimize=False, object_only=True)
        except SystemExit:
            pass                       # a refusal fixture: the errors are the point
    finally:
        sawc_mod.TypeChecker = base
    basename = os.path.basename(path)
    out = []
    for tc in captured:
        for d in tc.transfer_decisions():
            src = d.site[0]
            if src is None or os.path.basename(src) == basename:
                out.append(d)
    return out


def main():
    problems = check_every_exit_records()
    if problems:
        print("TRANSFER-DECISION GATE FAILED — the funnel has an exit that "
              "records nothing.")
        print()
        for p in problems:
            print(f"  {p}")
        print()
        print("Every exit of the checkpoint must `return self._decide_transfer(")
        print("...)`, so that the ABSENCE of a ledger entry is a sound reading")
        print("of 'this boundary was never checked' (design 267 step 3).")
        return 1

    total = 0
    checks_run = 0
    failures = []
    with tempfile.TemporaryDirectory(prefix="sawdecide") as workdir:
        for fixture in FIXTURES:
            name, source, expectations = fixture[0], fixture[1], fixture[2]
            checks = fixture[3] if len(fixture) > 3 else ()
            decisions = compile_and_collect(source, workdir, name)
            total += len(decisions)
            failures.extend(f"{name}: {p}" for p in check_well_formed(decisions))
            seen = {(d.destination, d.action, d.source.kind) for d in decisions}
            for want in expectations:
                if want not in seen:
                    failures.append(
                        f"{name}: no decision with destination={want[0]!r} "
                        f"action={want[1]!r} source={want[2]!r}; recorded "
                        f"{sorted(seen)}")
            # The identity assertions. They read decisions recorded for the
            # fixture's OWN file only, which `compile_and_collect` already
            # filtered to — a std decision at the same line number would
            # otherwise answer for it.
            own = [d for d in decisions if d.site[0] is not None
                   and os.path.basename(d.site[0]) == f"{name}.saw"]
            for check in checks:
                checks_run += 1
                problem = check(own)
                if problem:
                    failures.append(f"{name}: {check.__name__}: {problem}")

    if failures:
        print("TRANSFER-DECISION GATE FAILED — the boundary matrix regressed.")
        print()
        for f in failures:
            print(f"  {f}")
        print()
        print("A missing row means a boundary stopped producing the decision it")
        print("used to, which is how an ownership position goes unchecked.")
        return 1

    print(f"transfer-decision gate: {len(FIXTURES)} boundary fixtures, "
          f"{checks_run} identity checks, {total} decisions, "
          f"every checkpoint exit recorded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

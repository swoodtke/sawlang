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
from ast_nodes import Function, Method                         # noqa: E402
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
# 1b. The retain annotations have ONE writer.
# ---------------------------------------------------------------------------

#: The annotations that carry a retain into codegen, and the funnel that must
#: be the only thing writing them.
RETAIN_ATTRS = ("needs_copy", "payload_needs_copy")
RETAIN_FUNNEL = "_stamp_retain"


def check_retain_has_one_writer():
    """Every write of a retain annotation goes through `_stamp_retain`.

    THE PROPERTY, and why it is static. A retain annotation is an OBLIGATION —
    codegen duplicates a value because one of these is set and for no other
    reason — and design 270's audit checks that the obligation survives every
    lowering. It can only do that if the obligation was RECORDED, and the only
    moment anything knows a retain is owed is the moment it is stamped.

    Revision 2 recorded it at the arm that decides instead, which reached the
    ordinary Copy-tier transfer and missed design 131's whole payload family:
    `_check_payload_read` stamps `payload_needs_copy` on an `o!` and the
    checkpoint files `delegated` with no obligation, so clearing that stamp
    dropped a real retain under a clean audit. A second patch at a second arm
    would have left a third arm to find. This makes the rule structural: a new
    producer cannot stamp a retain without recording it, because it cannot
    stamp a retain at all except through the funnel.

    Read from the source rather than promised in a comment, for the reason
    `check_every_exit_records` is: a prose promise rots at the next edit.
    """
    problems = []
    for root, _dirs, files in os.walk(os.path.join(REPO, "sawc")):
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            with open(path) as f:
                try:
                    tree = ast.parse(f.read())
                except SyntaxError:
                    continue
            funnels = [n for n in ast.walk(tree)
                       if isinstance(n, ast.FunctionDef)
                       and n.name == RETAIN_FUNNEL]
            inside = set()
            for fn in funnels:
                inside.update(id(n) for n in ast.walk(fn))
            rel = os.path.relpath(path, REPO)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Assign, ast.AugAssign)):
                    continue
                targets = (node.targets if isinstance(node, ast.Assign)
                           else [node.target])
                for t in targets:
                    if not isinstance(t, ast.Attribute):
                        continue
                    if t.attr not in RETAIN_ATTRS:
                        continue
                    if id(node) in inside:
                        continue
                    problems.append(
                        f"{rel}:{node.lineno}: `{t.attr}` is assigned directly; "
                        f"every retain stamp must go through "
                        f"`{RETAIN_FUNNEL}`, which is what records the "
                        f"obligation the preservation audit checks")
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


# ---------------------------------------------------------------------------
# 5. THE PRESERVATION AUDIT (design 270, SL-212) — does the program codegen
#    receives still carry the decision the checker made about it?
#
# Sections 1-4 are about the tree the TYPECHECKER saw. Four passes rewrite
# bodies between that tree and codegen's, and a decision keyed to an occurrence
# detaches the moment a pass replaces the node it names. The audit itself is
# `sawc/typechecker/preservation.py` — one entry point, four properties, its
# docstring naming the passes; this drives it over a corpus chosen so that every
# one of the four is actually exercised.
#
# NON-VACUITY IS ASSERTED, NOT ASSUMED. A lane that checks nothing passes just
# as quietly as one that checks everything, so the coverage counters are a GATE:
# if a refactor stops producing stamps, or antecedent links, or specialization
# resolutions, or coroutine-frame rewrites, this fails on the zero rather than
# passing on the silence.
# ---------------------------------------------------------------------------

#: One program per pass the audit fences. These are the design-270 conformance
#: rows, reused rather than duplicated: they already exercise the shapes and
#: they already have behavioural oracles, so a drift shows up in two places.
PRESERVATION_CORPUS = (
    ("specialization", "examples/conformance/"
                       "V93_specialization_judges_the_instance.saw"),
    ("coroutine transform", "examples/conformance/"
                            "V94_driven_body_keeps_the_sync_decision.saw"),
    ("capture materialization", "examples/conformance/"
                                "V95_materialized_capture_releases_once.saw"),
    ("specialization x transform", "examples/conformance/"
                                   "V98_driven_generic_judges_each_instance.saw"),
    # The coverage floor is what put this one here rather than taste: the four
    # conformance rows above exercise P1-P3 and produce ZERO coroutine-frame
    # REWRITE deferrals between them, so P4 was passing on an empty set. This
    # program has both families at once (5 rewrites, 14 syntheses), which is
    # what makes it the pass-4 witness.
    ("frame reads", "examples/coro_closure_capture_positions.saw"),
    # Every face of design 131's payload family in one compile, so the retain
    # obligations P1r reconciles are not all of one shape.
    ("payload producers", "examples/conformance/"
                          "V99_every_payload_read_retains_once.saw"),
)

#: The counters that must be NON-ZERO across the corpus, and the rule each one
#: keeps honest. A zero here means the audit ran and looked at nothing.
COVERAGE_FLOOR = {
    'stamps_checked': "P1 reconciled no `needs_copy` stamp at all",
    'deferred_emitted': "P2 saw no deferral in an emitted body",
    'antecedents': "P3 found no clone carrying an `origin_node_id`",
    'resolutions': "P3 saw no template deferral RESOLVED at an instance",
    'coro_rewrites': "P4 saw no coroutine-frame rewrite deferral",
    'cloned_occurrences': "P1b reconciled no cloned occurrence",
    'lowerings': "P1r checked no lowering obligation",
    'origin_stamps': "P5 checked no origin stamp",
}


def compile_and_audit(path):
    """Compile `path` and run the preservation audit over what codegen got."""
    from typechecker import preservation

    captured, final = [], []
    base_tc, base_run = sawc_mod.TypeChecker, sawc_mod.run_codegen

    class Spy(base_tc):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            captured.append(self)

    def run_spy(codegen, ast):
        final.append(ast)
        return base_run(codegen, ast)

    sawc_mod.TypeChecker = Spy
    sawc_mod.run_codegen = run_spy
    with tempfile.TemporaryDirectory(prefix="sawpreserve") as workdir:
        try:
            sawc_mod.compile_saw(path, os.path.join(workdir, "out"),
                                 optimize=False, object_only=True)
        except SystemExit:
            pass
        finally:
            sawc_mod.TypeChecker = base_tc
            sawc_mod.run_codegen = base_run
    if not final:
        return None
    decisions, obligations = [], {}
    for tc in captured:
        decisions.extend(tc.transfer_decisions())
        obligations.update(tc.retain_obligations())
    return preservation.audit_preservation(final[0], decisions, obligations)


#: The program the audit's own NEGATIVE TESTS mutate. V99 exists for this: it
#: holds ONE of every face of design 131's payload family — `o!`, both `??`
#: arms, `if let`, `guard let`, a `try`'s Ok payload — beside an ordinary
#: `needs_copy` transfer, so the per-producer mutation below covers the
#: MECHANISM rather than the two cases that happened to be noticed. V91 was the
#: r2 subject and covered only `TryExpr` and the final Copy arm, which is
#: exactly how the `ForceUnwrap` producer went untested.
NEGATIVE_TEST_PROGRAM = "examples/conformance/V99_every_payload_read_retains_once.saw"


def _audit_parts(path):
    """Compile once and hand back (program, decisions) for mutation."""
    from typechecker import preservation

    captured, final = [], []
    base_tc, base_run = sawc_mod.TypeChecker, sawc_mod.run_codegen

    class Spy(base_tc):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            captured.append(self)

    def run_spy(codegen, ast):
        final.append(ast)
        return base_run(codegen, ast)

    sawc_mod.TypeChecker = Spy
    sawc_mod.run_codegen = run_spy
    with tempfile.TemporaryDirectory(prefix="sawnegative") as workdir:
        try:
            sawc_mod.compile_saw(path, os.path.join(workdir, "out"),
                                 optimize=False, object_only=True)
        except SystemExit:
            pass
        finally:
            sawc_mod.TypeChecker = base_tc
            sawc_mod.run_codegen = run_spy and base_run
    if not final:
        return None, None, None, None
    decisions, obligations = [], {}
    for tc in captured:
        decisions.extend(tc.transfer_decisions())
        obligations.update(tc.retain_obligations())
    return preservation, final[0], decisions, obligations


def check_audit_detects():
    """THE AUDIT'S OWN NEGATIVE TESTS — break one obligation, assert it fires.

    A preservation audit is a detector, and a detector that has never been shown
    to fire is a claim rather than a gate. Both blockers on SL-212.p1 revision 1
    were FALSE NEGATIVES — the audit certified programs it should have flagged —
    and both came from one mechanism: a rule that takes its obligations FROM the
    thing it is checking cannot see that thing removed. So each rule that closes
    one of those holes carries a test here that removes exactly one obligation
    and asserts the audit reports it.

    The three mutations, each independent and each reverted:

      1. DELETE every record for ONE live cloned occurrence, siblings intact.
         The reviewer's probe: one `NoneLiteral` in a monomorphized `init`,
         unstamped, `take` at `struct field`, origin still template-judged. P1a
         skipped the instance (other decisions remained) and P3 iterated only
         surviving decisions, so the loss was invisible. P1b must see it.
      2. CLEAR `needs_copy` on one node whose decision requires it.
      3. CLEAR `payload_needs_copy` on one node whose decision requires it —
         the reviewer's second probe, where the emitted program stopped
         performing the SL-211 Ok-path retain (`got 7` with no `copy 7`) while
         the audit stayed green.

    Two and three are SEPARATE tests on purpose: they are different obligations
    at different nodes, and an aggregate stamp count cannot tell one dropped
    retain from none.
    """
    preservation, program, decisions, obligations = _audit_parts(
        os.path.join(REPO, NEGATIVE_TEST_PROGRAM))
    if program is None:
        return [f"the audit's negative tests could not compile "
                f"{NEGATIVE_TEST_PROGRAM}"]

    problems = []
    base = preservation.audit_preservation(program, decisions, obligations)
    if not base.ok:
        return [f"the negative-test program is not clean to begin with: "
                f"{base.findings[0]}"]

    nodes = {n.node_id: n for n in preservation.structural_walk(program)
             if getattr(n, 'node_id', None) is not None}
    owner, templates = preservation._declaration_owners(program)

    # --- 1. one cloned occurrence's records, siblings intact --------------
    by_node = {}
    for d in decisions:
        if d.key[0] is not None:
            by_node.setdefault(d.key[0], []).append(d)
    target = None
    for nid, ds in by_node.items():
        node = nodes.get(nid)
        decl = owner.get(nid)
        if node is None or decl is None:
            continue
        origin = getattr(node, 'origin_node_id', None)
        if origin is None or origin not in by_node:
            continue
        if getattr(decl, 'is_synthesized', False):
            continue
        if not preservation._is_emitted(decl, templates):
            continue
        odecl = owner.get(origin)
        if odecl is not None and odecl is decl:
            continue
        if any(d.lowering for d in ds):
            continue                      # unstamped only — the hard case
        if not all(d.action in ('take', 'move') for d in ds):
            continue
        siblings = [d for d in decisions
                    if d.key[0] != nid and owner.get(d.key[0]) is decl]
        if not siblings:
            continue                      # siblings must survive the deletion
        target = nid
        break
    if target is None:
        problems.append(
            "NEGATIVE TEST 1 has no subject: no live cloned occurrence with an "
            "unstamped take/move decision and surviving siblings was found, so "
            "the per-occurrence rule is untested")
    else:
        thinned = [d for d in decisions if d.key[0] != target]
        report = preservation.audit_preservation(program, thinned, obligations)
        if not any(f.rule == 'P1b' for f in report.findings):
            problems.append(
                f"NEGATIVE TEST 1 FAILED: every record for one live cloned "
                f"occurrence (node {target}) was deleted with its siblings "
                f"intact and the audit reported "
                f"{[f.rule for f in report.findings] or 'nothing'} — the "
                f"per-occurrence rule does not fire")

    # --- 2. one required annotation, PER PRODUCER ------------------------
    # THE SELECTOR IS THE OBLIGATION TABLE, and that is the whole point. R2
    # selected subjects by `d.lowering`, which only the final implicit-copy arm
    # populates — so the DELEGATED `o!` producer, whose missing obligation WAS
    # the bug, could not be chosen by the test that was supposed to find it. A
    # selector must never require the field whose absence is the defect.
    #
    # One mutation per distinct (producer node kind, annotation) pair the table
    # holds, so the family is covered as a CLASS and a new producer is tested
    # the day it appears rather than the day somebody remembers to add a case.
    by_pair = {}
    for nid, attr in obligations.items():
        node = nodes.get(nid)
        decl = owner.get(nid)
        if node is None or decl is None or not getattr(node, attr, False):
            continue
        by_pair.setdefault((type(node).__name__, attr), node)
    if not by_pair:
        problems.append(
            "NEGATIVE TEST 2 has no subjects: the retain-obligation table is "
            "empty, so no dropped retain is tested at all")
    for (kind, attr), node in sorted(by_pair.items()):
        setattr(node, attr, False)
        try:
            report = preservation.audit_preservation(
                program, decisions, obligations)
        finally:
            setattr(node, attr, True)
        if not any(f.rule == 'P1r' for f in report.findings):
            problems.append(
                f"NEGATIVE TEST FAILED: `{attr}` was cleared on a {kind} whose "
                f"retain the checker recorded, and the audit reported "
                f"{[f.rule for f in report.findings] or 'nothing'} — a dropped "
                f"retain at this producer is invisible")

    # The reviewer's own producer, named so the class test cannot quietly stop
    # covering the case that earned it.
    if ('ForceUnwrap', 'payload_needs_copy') not in by_pair:
        problems.append(
            "NEGATIVE TEST 2 never reached the `ForceUnwrap` producer, which is "
            "the one the SL-212 r2 review found unrecorded — the negative-test "
            "program must contain an `o!` whose payload retains")
    if ('Identifier', 'needs_copy') not in by_pair:
        problems.append(
            "NEGATIVE TEST 2 never reached an ordinary `needs_copy` transfer, "
            "so the two annotations are not being pinned separately")

    # --- 4. one cleared origin stamp -------------------------------------
    # The THIRD instance of the mechanism: P1b and P3 take their subject from
    # `origin_node_id`, so clearing one removes an occurrence from the audit's
    # universe rather than failing a check. P5 fences it, and this is the proof.
    victim = None
    for decl in preservation.structural_walk(program):
        if not isinstance(decl, (Function, Method)):
            continue
        if not getattr(decl, 'is_mono_instance', False):
            continue
        for node in preservation.structural_walk(decl):
            if node is decl:
                continue
            if getattr(node, 'origin_node_id', None) is not None:
                victim = node
                break
        if victim is not None:
            break
    if victim is None:
        problems.append(
            "NEGATIVE TEST 4 has no subject: no node inside a monomorphized "
            "instance body carries an `origin_node_id`, so the origin universe "
            "is untested")
    else:
        saved = victim.origin_node_id
        victim.origin_node_id = None
        try:
            report = preservation.audit_preservation(
                program, decisions, obligations)
        finally:
            victim.origin_node_id = saved
        if not any(f.rule == 'P5' for f in report.findings):
            problems.append(
                f"NEGATIVE TEST 4 FAILED: `origin_node_id` was cleared on one "
                f"node of a monomorphized instance body and the audit reported "
                f"{[f.rule for f in report.findings] or 'nothing'} — the origin "
                f"universe can be shrunk without the audit noticing")

    # The program must be clean again once every mutation is reverted, or the
    # tests above are measuring their own residue.
    after = preservation.audit_preservation(program, decisions, obligations)
    if not after.ok:
        problems.append(
            f"the negative tests left residue: {after.findings[0]}")
    return problems


def check_preservation():
    """Run the audit over the corpus; return (problems, totals)."""
    problems = []
    totals = {k: 0 for k in COVERAGE_FLOOR}
    for label, rel in PRESERVATION_CORPUS:
        path = os.path.join(REPO, rel)
        if not os.path.exists(path):
            problems.append(f"{label}: {rel} is missing from the corpus")
            continue
        report = compile_and_audit(path)
        if report is None:
            problems.append(f"{label}: {rel} produced no program to audit")
            continue
        for key in totals:
            totals[key] += report.counts.get(key, 0)
        for finding in report.findings:
            problems.append(f"{label} ({os.path.basename(rel)}): {finding}")
    for key, why in COVERAGE_FLOOR.items():
        if totals[key] == 0:
            problems.append(
                f"COVERAGE: `{key}` is zero across the whole corpus — {why}. "
                f"The audit passed VACUOUSLY, which is not a pass")
    return problems, totals


def main():
    problems = check_every_exit_records() + check_retain_has_one_writer()
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

    preservation_problems, totals = check_preservation()
    preservation_problems = preservation_problems + check_audit_detects()
    if preservation_problems:
        print("TRANSFER-DECISION GATE FAILED — a lowering pass dropped, "
              "duplicated or detached a decision.")
        print()
        for p in preservation_problems:
            print(f"  {p}")
        print()
        print("The program handed to codegen must still carry the decision the")
        print("checker made about it (design 270). The audit is")
        print("`sawc/typechecker/preservation.py`; its docstring names the four")
        print("passes and what each property fences.")
        return 1

    print(f"transfer-decision gate: {len(FIXTURES)} boundary fixtures, "
          f"{checks_run} identity checks, {total} decisions, "
          f"every checkpoint exit recorded.")
    print(f"preservation audit: {len(PRESERVATION_CORPUS)} programs, "
          + ", ".join(f"{v} {k}" for k, v in sorted(totals.items()))
          + "; no decision detached.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Coroutine-transform differential harness (design 218 unit 0).

THE ORACLE IS A TWIN. Every generated program comes in two versions with the
SAME value flow: the DRIVEN one suspends, the CONTROL one does not. Adding a
suspension to a program is not supposed to change what it prints, what it
returns, or how many times anything is destroyed — so any difference between
the twins is a coroutine-transform bug, and no model of what the program
"should" do is needed to see it. That is the whole reason this instrument
exists: the DF-217 family are ownership bugs in generated code, and generated
code is exactly what no reader reviews.

THE COMPILE FLOOR runs FIRST, ahead of every combo: the shared PRELUDE must
compile on its own, or the run fails outright (`check_prelude`). Check 2 below
exempts a pair whose twins refuse identically, which is right for a shape the
language refuses and blind to a prelude that has gone stale — and since the
corpus is GENERATED, nothing else in the tree ever compiles these declarations.
That blind spot took the whole lane down twice while the battery stayed green
(design 219 wave B's rename; design 234's fallible `Arc(value:)`, DF-284a).
THE DEAD-CONTEXT CHECK runs LAST and is the same assertion one level down: a
context every one of whose pairs refused on both twins is a wrapper that stopped
compiling, and it fails the run too. The floor cannot see one, because the
prelude is fine; two contexts were in that state when the check was written.

FOUR CHECKS, in the order they are applied:

  1. A traceback, an `internal compiler error`, a compile hang or a run hang is
     a finding on EITHER twin, parity or no parity. Nonsense is not the input
     here — these are well-formed programs.
  2. COMPILE PARITY: one twin refusing while the other compiles is a finding
     (a BOGUS-REFUSAL where the driven twin is the refuser — DF-217g's shape).
     Both refusing identically is not.
  3. RUN PARITY: exit code, and stdout including the `NEW <id>` / `DEINIT <id>`
     witness lines. This is the strongest check and the one that found
     DF-217a/b/h.
  4. WITNESS EXACTLY-ONCE, per twin, independent of parity: for every witness
     id, `count(DEINIT id) == count(NEW id)`. More deinits than creations is a
     DOUBLE-FREE; fewer is a LEAK. This is what carries the axes where parity
     CANNOT apply — a cancelled task legitimately prints different lines from
     an uncancelled one, but it may not free a frame slot twice.

WITNESS TIERS. Only two of the five copy tiers can witness their own
destruction without confusing a legitimate copy for a double free: `nocopy`
(`Res`, a hand-written deinit) and `tag` (`Tag`, a DECLARED `Copy` struct
over an `Arc<Res>` — a copy RETAINS, so the payload still dies exactly once).
`tag` is why a retain-tier over-release is visible here at all; the previous
harness's retain tier was a plain `struct Bag { s: String }` with nothing
to count, and said so in its own gap list. `trivial`, `implicit` (that same
`Bag`, kept because DF-217c's extension was found on it) and `explicit`
(`Vector<Int>`) carry the parity checks only.

DETERMINISM. The combo space is a sorted product of four axes and nothing
reads a clock, a PID or `os.urandom`. `--quick` takes a stratified sample that
is a pure function of `--seed`: it first covers every value of every axis at
least once, then fills to the requested size. So the battery lane runs the same
60 pairs on every machine, and `--replay <tag>` rebuilds any one pair alone.

WAVE-BOUNDED FAN-OUT. Compiles and runs are launched in waves of `--jobs` and
every wave is fully reaped before the next starts. DF-182f took a machine to
loadavg 700 because a tool lost a throttle by accident; there is no path here
that spawns without counting.

    tools/corodiff.py --quick            # ~60 pairs, the battery mode
    tools/corodiff.py --all              # the whole cross
    tools/corodiff.py --quick 20 --jobs 4
    tools/corodiff.py --filter place_write_set
    tools/corodiff.py --replay let_shadow_rebind__nocopy__before__susp_main
    tools/corodiff.py --list-axes

A finding is written to `--findings` (default `.build/corodiff-findings/`) as
its two twins plus a `.txt` report holding the combo that generated it, both
twins' behaviour, and the replay command. Findings are deduplicated by
signature, so one bug reached from thirty combos writes one report.

THE WORKFLOW is the ordinary one (TESTING.md): file it as a DF, pin the repro
in `examples/` under a name that says what BEHAVIOR it pins, XFAIL it citing
the DF, and add the signature to `tools/corodiff_known.txt` — this tool's XFAIL
ledger. A listed signature is still reported, with its DF number, but does not
fail the run, so the lane stays a signal rather than a wall. An entry that no
longer fires is stale exactly as an XPASS marker is; `--ignore-known` re-reports
everything, which is how you check.
"""
import argparse
import itertools
import os
import random
import re
import shutil
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SAWC = os.path.join(REPO, "sawc", "sawc.py")
DEFAULT_FINDINGS = os.path.join(REPO, ".build", "corodiff-findings")
# Per-PROCESS scratch. Two corodiff runs at once — a chunked sweep beside a
# targeted `--filter`, which is the natural way to work — would otherwise write
# each other's `w0__driven.saw` and read each other's binaries, and the results
# are not wrong-looking, they are wrong. Nothing about the SELECTION of what to
# test reads the pid; only where the scratch lands does.
WORK_DIR = os.path.join(REPO, ".build", "corodiff-work", str(os.getpid()))
KNOWN_FILE = os.path.join(REPO, "tools", "corodiff_known.txt")

ICE_MARK = "internal compiler error"
TRACEBACK_MARK = "Traceback (most recent call last)"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


# ---------------------------------------------------------------------------
# The shared declarations every generated program carries.
#
# One prelude for all five tiers, so a combo differs from its neighbours only
# in the body — which is what makes a finding's tag readable as a description
# of the bug rather than of the file.
# ---------------------------------------------------------------------------

PRELUDE = '''import std.task.{yield_now}

struct Res {
    name: String
}
extension Res: NoCopy {
    func deinit(&var self) {
        print("DEINIT {self.name}")
    }
}
extension Res {
    func label(&self) -> String { self.name }
}

struct Bag {
    s: String
}

struct Tag {
    cell: Arc<Res>
}
@synthesize
extension Tag: Copy {}

func mk_triv(id: Int) -> Int { id }
func mk_triv_s(id: Int) -> Int {
    yield_now()
    id
}
func mk_bag(id: Int) -> Bag { Bag(s: "b{id}") }
func mk_bag_s(id: Int) -> Bag {
    yield_now()
    Bag(s: "b{id}")
}
func mk_tag(id: Int) -> Tag {
    print("NEW t{id}")
    Tag(cell: try! Arc<Res>(value: Res(name: "t{id}")))
}
func mk_tag_s(id: Int) -> Tag {
    yield_now()
    print("NEW t{id}")
    Tag(cell: try! Arc<Res>(value: Res(name: "t{id}")))
}
func mk_vec(id: Int) -> Vector<Int> { [id, id + 1] }
func mk_vec_s(id: Int) -> Vector<Int> {
    yield_now()
    [id, id + 1]
}
func mk_res(id: Int) -> Res {
    print("NEW r{id}")
    Res(name: "r{id}")
}
func mk_res_s(id: Int) -> Res {
    yield_now()
    print("NEW r{id}")
    Res(name: "r{id}")
}

func mk_triv_opt(id: Int) -> Int? { mk_triv(id) }
func mk_bag_opt(id: Int) -> Bag? { mk_bag(id) }
func mk_tag_opt(id: Int) -> Tag? { mk_tag(id) }
func mk_vec_opt(id: Int) -> Vector<Int>? { mk_vec(id) }
func mk_res_opt(id: Int) -> Res? { mk_res(id) }

func mk_none_trivial() -> Int? { None }
func mk_none_implicit() -> Bag? { None }
func mk_none_tag() -> Tag? { None }
func mk_none_explicit() -> Vector<Int>? { None }
func mk_none_nocopy() -> Res? { None }

func derive_triv(x: Int) -> Int { x + 1000 }
func derive_bag(x: Bag) -> Bag { Bag(s: "d{x.s}") }
func derive_tag(x: Tag) -> Tag {
    print("NEW d{x.cell.label()}")
    Tag(cell: try! Arc<Res>(value: Res(name: "d{x.cell.label()}")))
}
func derive_vec(x: Vector<Int>) -> Vector<Int> { move x }
func derive_res(x: Res) -> Res {
    print("NEW d{x.name}")
    Res(name: "d{x.name}")
}

enum Wrap_Trivial { case Has(x: Int) }
enum Wrap_Implicit { case Has(x: Bag) }
enum Wrap_Tag { case Has(x: Tag) }
enum Wrap_Explicit { case Has(x: Vector<Int>) }
enum Wrap_Nocopy { case Has(x: Res) }
@synthesize
extension Wrap_Explicit: ExplicitCopy {}
extension Wrap_Nocopy: NoCopy {}

struct Holder {
    n: Int
}

func run_int(body: () sync -> Int) -> Int { body() }

// The NESTED-GENERIC pair (design 218c stage 0, DF-258a). `ghop_s` suspends
// UNCONDITIONALLY and calls no method on its type parameter, so its
// instantiation gets no effect node and the coroutine transform DECLINES to
// promote it (218b landing note (c)) — codegen's late monomorphization is what
// serves the call, and it compiles the body as a plain function with the yield
// erased. `ghop` is the sync sibling `desuspend` rewrites to, so the control
// twin carries the same value flow through the same generic.
func ghop<T>(x: T) -> T { x }
func ghop_s<T>(x: T) -> T {
    yield_now()
    x
}
'''


# ---------------------------------------------------------------------------
# Axis 1: the copy TIERS.
# ---------------------------------------------------------------------------

class Tier:
    def __init__(self, name, saw_type, sync_fn, susp_fn, opt_fn, none_fn,
                 derive_fn, wrap_enum, use, needs_move, witnesses):
        self.name = name
        self.saw_type = saw_type
        self.sync_fn = sync_fn
        self.susp_fn = susp_fn
        self.opt_fn = opt_fn
        self.none_fn = none_fn
        self.derive_fn = derive_fn
        self.wrap_enum = wrap_enum
        self._use = use
        self.needs_move = needs_move
        # True when this tier's values print `NEW`/`DEINIT` lines a copy cannot
        # forge: NoCopy (no copy exists) and Copy-over-Arc (a copy is a
        # retain, so the payload still dies once).
        self.witnesses = witnesses

    def make(self, id_, suspend):
        return f"{self.susp_fn if suspend else self.sync_fn}({id_})"

    def use(self, var):
        return self._use(var)

    def transfer(self, var):
        """The spelling that moves `var` at this tier."""
        return f"move {var}" if self.needs_move else var


TIERS = [
    Tier("trivial", "Int", "mk_triv", "mk_triv_s", "mk_triv_opt",
         "mk_none_trivial", "derive_triv", "Wrap_Trivial",
         lambda v: f'print("val {{{v}}}")', needs_move=False, witnesses=False),
    Tier("implicit", "Bag", "mk_bag", "mk_bag_s", "mk_bag_opt",
         "mk_none_implicit", "derive_bag", "Wrap_Implicit",
         lambda v: f'print("val {{{v}.s}}")', needs_move=False, witnesses=False),
    Tier("tag", "Tag", "mk_tag", "mk_tag_s", "mk_tag_opt",
         "mk_none_tag", "derive_tag", "Wrap_Tag",
         lambda v: f'print("val {{{v}.cell.label()}}")', needs_move=False,
         witnesses=True),
    Tier("explicit", "Vector<Int>", "mk_vec", "mk_vec_s", "mk_vec_opt",
         "mk_none_explicit", "derive_vec", "Wrap_Explicit",
         lambda v: f'print("val {{{v}.len()}}")', needs_move=True,
         witnesses=False),
    Tier("nocopy", "Res", "mk_res", "mk_res_s", "mk_res_opt",
         "mk_none_nocopy", "derive_res", "Wrap_Nocopy",
         lambda v: f'print("val {{{v}.name}}")', needs_move=True,
         witnesses=True),
]

TIER_BY_NAME = {t.name: t for t in TIERS}


# ---------------------------------------------------------------------------
# Axis 2: the BINDING constructs.
#
# Each builder returns `(lines, prune_reason)`; a builder that cannot express
# the requested placement returns `(None, reason)` and the reason is logged, so
# the prune count is auditable rather than a silent gap.
# ---------------------------------------------------------------------------

def st_let(t, placement, ctx):
    lines = []
    if placement == "before":
        lines.append("yield_now()")
    lines.append(f"let v1 = {t.make(1, placement == 'in_rhs')}")
    if placement == "between":
        lines.append("yield_now()")
    lines.append(t.use("v1"))
    if placement == "after":
        lines.append("yield_now()")
    return lines, None


def st_let_shadow_rebind(t, placement, ctx):
    lines = [f"let v1 = {t.make(1, placement == 'in_rhs')}"]
    if placement == "before":
        lines.append("yield_now()")
    lines.append(t.use("v1"))
    if placement == "between":
        lines.append("yield_now()")
    lines.append(f"let v1 = {t.derive_fn}({t.transfer('v1')})")
    if placement == "after":
        lines.append("yield_now()")
    lines.append(t.use("v1"))
    return lines, None


def st_let_rebind_distinct(t, placement, ctx):
    lines = [f"let v1 = {t.make(1, placement == 'in_rhs')}"]
    if placement == "before":
        lines.append("yield_now()")
    lines.append(t.use("v1"))
    if placement == "between":
        lines.append("yield_now()")
    lines.append(f"let v2 = {t.derive_fn}({t.transfer('v1')})")
    if placement == "after":
        lines.append("yield_now()")
    lines.append(t.use("v2"))
    return lines, None


def st_if_let_payload(t, placement, ctx):
    if placement == "in_rhs":
        return None, "if_let_payload: the optional helpers are sync-only"
    lines = []
    if placement == "before":
        lines.append("yield_now()")
    inner = []
    if placement == "between":
        inner.append("yield_now()")
    inner.append(t.use("v1"))
    if placement == "after":
        inner.append("yield_now()")
    lines.append(f"if let v1 = {t.opt_fn}(1) {{")
    lines += ["    " + l for l in inner]
    lines.append("}")
    return lines, None


def st_if_let_move_local(t, placement, ctx):
    if placement == "in_rhs":
        return None, "if_let_move_local: the scrutinee is `move <local>`, not a call"
    lines = [f"var ov1 = {t.opt_fn}(1)"]
    if placement == "before":
        lines.append("yield_now()")
    inner = []
    if placement == "between":
        inner.append("yield_now()")
    inner.append(t.use("v2"))
    if placement == "after":
        inner.append("yield_now()")
    lines.append("if let v2 = move ov1 {")
    lines += ["    " + l for l in inner]
    lines.append("}")
    return lines, None


def st_guard_let(t, placement, ctx):
    if placement == "in_rhs":
        return None, "guard_let: the optional helpers are sync-only"
    lines = []
    if placement == "before":
        lines.append("yield_now()")
    lines.append(f"guard let v1 = {t.opt_fn}(1) else {{ {ctx.void_return} }}")
    if placement == "between":
        lines.append("yield_now()")
    lines.append(t.use("v1"))
    if placement == "after":
        lines.append("yield_now()")
    return lines, None


def st_match_consume(t, placement, ctx):
    lines = []
    if placement == "before":
        lines.append("yield_now()")
    lines.append(f"match {t.wrap_enum}.Has(x: {t.make(1, placement == 'in_rhs')}) {{")
    inner = []
    if placement == "between":
        inner.append("yield_now()")
    inner.append(t.use("x"))
    if placement == "after":
        inner.append("yield_now()")
    lines.append("    case Has(x) -> {")
    lines += ["        " + l for l in inner]
    lines.append("    }")
    lines.append("}")
    return lines, None


def st_match_nobinding(t, placement, ctx):
    lines = []
    if placement == "before":
        lines.append("yield_now()")
    lines.append(f"match {t.wrap_enum}.Has(x: {t.make(1, placement == 'in_rhs')}) {{")
    inner = []
    if placement == "between":
        inner.append("yield_now()")
    inner.append('print("matched")')
    if placement == "after":
        inner.append("yield_now()")
    lines.append("    case Has(_) -> {")
    lines += ["        " + l for l in inner]
    lines.append("    }")
    lines.append("}")
    return lines, None


def st_match_borrow(t, placement, ctx):
    """The match-arm-RETAIN axis: an arm binding a payload IN PLACE.

    The previous harness never implemented this and listed it as a gap. It is
    the design-146 borrowing match (DF-146d): the scrutinee is a PLACE the
    container still owns, so the arm's binding is a borrow rather than a
    consume, and the copy tier is consulted for that one binding. Whether the
    transform preserves that distinction across a suspend is exactly the sort
    of thing no ownership check downstream of it can see.
    """
    if placement == "in_rhs":
        return None, "match_borrow: the scrutinee is a place, not a call"
    if placement in ("between", "after"):
        return None, ("match_borrow: a borrowing arm's body runs inside a place "
                      "WINDOW, and a window is `sync` by design (141) — a "
                      "suspension there is a deliberate refusal, not a twin")
    lines = [
        f"var slots1: Vector<{t.wrap_enum}> = "
        f"[{t.wrap_enum}.Has(x: {t.make(1, False)})]"
    ]
    if placement == "before":
        lines.append("yield_now()")
    inner = []
    if placement == "between":
        inner.append("yield_now()")
    inner.append(t.use("x"))
    if placement == "after":
        inner.append("yield_now()")
    lines.append("match slots1[0] {")
    lines.append("    case Has(x) -> {")
    lines += ["        " + l for l in inner]
    lines.append("    }")
    lines.append("}")
    return lines, None


def st_tuple_destructure(t, placement, ctx):
    susp = placement == "in_rhs"
    lines = []
    if placement == "before":
        lines.append("yield_now()")
    lines.append(f"let (a1, b1) = ({t.make(1, susp)}, {t.make(2, susp)})")
    if placement == "between":
        lines.append("yield_now()")
    lines.append(t.use("a1"))
    lines.append(t.use("b1"))
    if placement == "after":
        lines.append("yield_now()")
    return lines, None


def st_nested_tuple_destructure(t, placement, ctx):
    susp = placement == "in_rhs"
    lines = []
    if placement == "before":
        lines.append("yield_now()")
    lines.append(f"let ((a1, b1), c1) = (({t.make(1, susp)}, {t.make(2, susp)}), "
                 f"{t.make(3, susp)})")
    if placement == "between":
        lines.append("yield_now()")
    lines.append(t.use("a1"))
    lines.append(t.use("b1"))
    lines.append(t.use("c1"))
    if placement == "after":
        lines.append("yield_now()")
    return lines, None


def st_let_underscore(t, placement, ctx):
    if placement == "between":
        return None, "let_underscore: nothing is bound, so there is no between"
    lines = []
    if placement == "before":
        lines.append("yield_now()")
    lines.append(f"let _ = {t.make(1, placement == 'in_rhs')}")
    if placement == "after":
        lines.append("yield_now()")
    lines.append('print("discarded")')
    return lines, None


def st_coalesce_rhs(t, placement, ctx):
    if placement == "between":
        return None, "coalesce_rhs: the bind and the use are one statement apart"
    lines = []
    if placement == "before":
        lines.append("yield_now()")
    lines.append(f"let v1 = {t.none_fn}() ?? {t.make(1, placement == 'in_rhs')}")
    if placement == "after":
        lines.append("yield_now()")
    lines.append(t.use("v1"))
    return lines, None


def st_closure_capture_implicit(t, placement, ctx):
    if placement == "in_rhs":
        return None, "closure_capture_implicit: covered by `let` at in_rhs"
    lines = [f"let v1 = {t.make(1, False)}"]
    if placement == "before":
        lines.append("yield_now()")
    lines.append(f"let f1 = {{ {t.use('v1')} }}")
    if placement == "between":
        lines.append("yield_now()")
    lines.append("f1()")
    if placement == "after":
        lines.append("yield_now()")
    return lines, None


def st_closure_capture_move(t, placement, ctx):
    if placement == "in_rhs":
        return None, "closure_capture_move: covered by `let` at in_rhs"
    lines = [f"let v1 = {t.make(1, False)}"]
    if placement == "before":
        lines.append("yield_now()")
    lines.append(f"let f1 = {{ [move v1] in {t.use('v1')} }}")
    if placement == "between":
        lines.append("yield_now()")
    lines.append("f1()")
    if placement == "after":
        lines.append("yield_now()")
    return lines, None


def st_closure_capture_self(t, placement, ctx):
    """A closure naming `self` — DF-216g's shape, and only legal in a method.

    Kept as its own binding rather than folded into a context so the harness
    reports it by name: the sync case landed with design 216 and the SUSPENDING
    one is the open finding, which is precisely a driven-vs-control difference.
    """
    if not ctx.has_self:
        return None, "closure_capture_self: needs a method context"
    if placement == "in_rhs":
        return None, "closure_capture_self: the capture is a receiver, not a call"
    lines = [f"let v1 = {t.make(1, False)}"]
    if placement == "before":
        lines.append("yield_now()")
    # Passed STRAIGHT to the call that runs it — binding it to a `let` would be
    # the escaping form design 216 refuses on both twins, which would hide the
    # suspending case rather than test it.
    lines.append('print("self {}", run_int({ self.n + 1 }))')
    if placement == "between":
        lines.append("yield_now()")
    lines.append(t.use("v1"))
    if placement == "after":
        lines.append("yield_now()")
    return lines, None


def st_place_write_index(t, placement, ctx):
    if placement == "in_rhs":
        return None, ("place_write_index: index-assignment routes the RHS "
                      "through a `sync` place window (141), so a suspending RHS "
                      "is a deliberate refusal — `place_write_set` is the "
                      "spelling that ACCEPTS one, and mishandles it")
    lines = [f"var arr1: Vector<{t.saw_type}> = "
             f"[{t.make(1, False)}, {t.make(2, False)}]"]
    if placement == "before":
        lines.append("yield_now()")
    lines.append(f"arr1[0] = {t.make(3, placement == 'in_rhs')}")
    if placement == "between":
        lines.append("yield_now()")
    lines.append(t.use("arr1[0]"))
    if placement == "after":
        lines.append("yield_now()")
    return lines, None


def st_place_write_set(t, placement, ctx):
    lines = [f"var arr1: Vector<{t.saw_type}> = "
             f"[{t.make(1, False)}, {t.make(2, False)}]"]
    if placement == "before":
        lines.append("yield_now()")
    lines.append(f"arr1.set(0, {t.make(3, placement == 'in_rhs')})")
    if placement == "between":
        lines.append("yield_now()")
    lines.append(t.use("arr1[0]"))
    if placement == "after":
        lines.append("yield_now()")
    return lines, None


def st_swap_out(t, placement, ctx):
    lines = [f"var arr1: Vector<{t.saw_type}> = "
             f"[{t.make(1, False)}, {t.make(2, False)}]"]
    if placement == "before":
        lines.append("yield_now()")
    lines.append(f"let old1 = arr1.swap_out(0, {t.make(3, placement == 'in_rhs')})")
    if placement == "between":
        lines.append("yield_now()")
    lines.append(t.use("old1"))
    lines.append(t.use("arr1[0]"))
    if placement == "after":
        lines.append("yield_now()")
    return lines, None


def st_optional_take(t, placement, ctx):
    if placement == "in_rhs":
        return None, "optional_take: the optional helpers are sync-only"
    lines = [f"var ov1 = {t.opt_fn}(1)"]
    if placement == "before":
        lines.append("yield_now()")
    lines.append("let taken1 = ov1.take()")
    if placement == "between":
        lines.append("yield_now()")
    lines.append(f"if let t1 = taken1 {{")
    lines.append("    " + t.use("t1"))
    lines.append("}")
    if placement == "after":
        lines.append("yield_now()")
    return lines, None


BINDINGS = [
    ("let", st_let),
    ("let_shadow_rebind", st_let_shadow_rebind),
    ("let_rebind_distinct", st_let_rebind_distinct),
    ("if_let_payload", st_if_let_payload),
    ("if_let_move_local", st_if_let_move_local),
    ("guard_let", st_guard_let),
    ("match_consume", st_match_consume),
    ("match_nobinding", st_match_nobinding),
    ("match_borrow", st_match_borrow),
    ("tuple_destructure", st_tuple_destructure),
    ("nested_tuple_destructure", st_nested_tuple_destructure),
    ("let_underscore", st_let_underscore),
    ("coalesce_rhs", st_coalesce_rhs),
    ("closure_capture_implicit", st_closure_capture_implicit),
    ("closure_capture_move", st_closure_capture_move),
    ("closure_capture_self", st_closure_capture_self),
    ("place_write_index", st_place_write_index),
    ("place_write_set", st_place_write_set),
    ("swap_out", st_swap_out),
    ("optional_take", st_optional_take),
]

BINDING_BY_NAME = dict(BINDINGS)

# Axis 3.
PLACEMENTS = ["before", "after", "between", "in_rhs"]

# The subset the contexts that are not run at full cross use. Chosen for
# coverage of the mechanisms rather than of the grammar: one plain binding, the
# two frame-field-identity shapes, both match flavours, a closure capture, both
# place writes, and the optional move-out.
CURATED_BINDINGS = [
    "let", "let_shadow_rebind", "if_let_move_local", "match_consume",
    "match_borrow", "closure_capture_move", "place_write_index",
    "place_write_set", "optional_take",
]
CURATED_TIERS = ["nocopy", "tag"]
CURATED_PLACEMENTS = ["before", "in_rhs"]


# ---------------------------------------------------------------------------
# Axis 4: the CONTEXT the body runs in.
#
# A context owns three things: the wrapper it puts the body in, an optional
# transform of the body itself (the cancellation contexts insert an observation
# point), and WHICH CHECKS APPLY. The last is the part that matters: a
# cancelled task and its uncancelled twin legitimately print different lines,
# so those contexts run the witness oracle and not stdout parity. Saying which
# checks a context can carry is how a new axis gets added without either
# weakening the strong ones or drowning the run in false parity reports.
# ---------------------------------------------------------------------------

class Context:
    def __init__(self, name, wrap, *, oracle_class="linear",
                 stdout_parity="exact", leak_check=True,
                 void_return="return", has_self=False, full_cross=False,
                 body_transform=None, excludes=(), note=""):
        self.name = name
        # Contexts sharing a class share a MECHANISM, and a finding's signature
        # is keyed by the class rather than by the context: the loop-iteration
        # drift is a property of being in a loop, not of `loop_second_iter`, and
        # a ledger entry that said `loop_second_iter` would go stale the moment
        # a second loop context was added.
        self.oracle_class = oracle_class
        self._wrap = wrap
        self.stdout_parity = stdout_parity     # "exact" | "sorted" | "off"
        self.leak_check = leak_check
        self.void_return = void_return
        self.has_self = has_self
        self.full_cross = full_cross
        self.body_transform = body_transform
        self.excludes = set(excludes)
        self.note = note

    def wrap(self, body_lines):
        return self._wrap(body_lines)


def _indent(lines, n):
    pad = " " * n
    return "\n".join(pad + l for l in lines)


# Printed by every wrapper immediately AFTER the scope holding the body closes.
#
# Without it a whole class is invisible: a frame local whose scope ends inside
# the body — a loop iteration, a closure call, a method call — may be released
# late by the driven twin and on time by the control twin, and if nothing is
# printed between the late release and the end of the program the two stdouts
# still match. The marker is the ruler the release points are measured against.
CLOSED = 'print("scope closed")'


def _worker(body_lines, name="worker"):
    return (f"func {name}() -> Int {{\n{_indent(body_lines, 4)}\n"
            f"    {CLOSED}\n    0\n}}\n")


def w_susp_main(body):
    return f"func main() {{\n{_indent(body, 4)}\n    {CLOSED}\n}}\n"


def w_taskgroup_spawn(body):
    return _worker(body) + (
        "\nfunc main() {\n"
        "    var g = TaskGroup()\n"
        "    let h = g.spawn(worker())\n"
        '    print("joined {h.join()}")\n'
        f"    {CLOSED}\n"
        "}\n"
    )


def w_nested_block_tail(body):
    """The body in a nested SCOPE that closes before the marker prints.

    Written as an inner `if true { ... }` rather than the immediately-invoked
    closure `{ ... }()` it used to be: that spelling does not parse (DF-284b —
    the postfix call is never applied to a closure literal, in any position),
    so every one of this context's pairs refused on both twins and check 2
    scored them clean. The closure DIMENSION is `closure_from_driven`'s; what
    this row measures is scope-end release timing at a nested scope, which the
    inner `if` gives with nothing else in the way.
    """
    return (
        "func main() {\n"
        "    if true {\n"
        "        if true {\n" + _indent(body, 12) + "\n        }\n"
        f"        {CLOSED}\n"
        "    }\n"
        "}\n"
    )


def w_loop_second_iter(body):
    return (
        "func main() {\n"
        "    var i = 0\n"
        "    while i < 2 {\n" + _indent(body, 8) + "\n"
        "        i = i + 1\n"
        "    }\n"
        f"    {CLOSED}\n"
        "}\n"
    )


# THE RANGE-`for` LOOPS, both flavours (DF-225m).
#
# A `while` loop is the one loop shape the harness had, and it is the one shape
# the coroutine transform does NOT rewrite: `_split_while` re-emits the author's
# own condition, while `_split_for` HAND-WRITES the header and the step out of
# frame slots, because a driven body has no `Range`/`RangeInclusive` object to
# hold the iteration state across a suspension. So the whole range lowering —
# the half of looping that has a compiler-authored control flow — sat outside
# this instrument, and DF-225m (an inclusive `for` in a driven body dropping its
# last iteration, silently, since the sync twin was right) lived there for as
# long as it did because `grep '\.\.=' tools/corodiff.py` came back empty.
#
# THREE contexts, not one, because the inclusive lowering has three answers to
# get wrong and only the first is a plain iteration count:
#   * `..=` over two iterations — the ordinary shape.
#   * `..=` over ONE — DF-225m's loudest row, which ran the body ZERO times.
#   * `..` over two — the exclusive control, so a regression in the shared
#     header/step code is attributable to a flavour rather than to `for`.
# All three share `oracle_class="loop"` with `loop_second_iter`: the class names
# a MECHANISM (a body that runs more than once), and keying the ledger on the
# context name instead would have gone stale the moment this was added — which
# is what the class comment on `Context` has said since design 218.
def w_loop_for_inclusive(body):
    return (
        "func main() {\n"
        "    for i in 1..=2 {\n" + _indent(body, 8) + "\n"
        "    }\n"
        f"    {CLOSED}\n"
        "}\n"
    )


def w_loop_for_inclusive_once(body):
    return (
        "func main() {\n"
        "    for i in 1..=1 {\n" + _indent(body, 8) + "\n"
        "    }\n"
        f"    {CLOSED}\n"
        "}\n"
    )


def w_loop_for_exclusive(body):
    return (
        "func main() {\n"
        "    for i in 0..2 {\n" + _indent(body, 8) + "\n"
        "    }\n"
        f"    {CLOSED}\n"
        "}\n"
    )


def w_closure_from_driven(body):
    return (
        "func main() {\n"
        "    let f = {\n" + _indent(body, 8) + "\n    }\n"
        "    f()\n"
        f"    {CLOSED}\n"
        "}\n"
    )


def w_method_driven(body):
    return (
        "extension Holder {\n"
        "    func run(&var self) {\n" + _indent(body, 8) + "\n"
        "    }\n"
        "}\n"
        "\nfunc main() {\n"
        "    var h = Holder(n: 7)\n"
        "    h.run()\n"
        f"    {CLOSED}\n"
        "}\n"
    )


def w_cancel_mid_suspend(body):
    return _worker(body) + (
        "\nfunc main() {\n"
        "    var g = TaskGroup()\n"
        "    let h = g.spawn(worker())\n"
        "    yield_now()\n"
        "    h.cancel()\n"
        '    print("joined {h.join()}")\n'
        "}\n"
    )


def w_cancel_before_start(body):
    return _worker(body) + (
        "\nfunc main() {\n"
        "    var g = TaskGroup()\n"
        "    let h = g.spawn(worker())\n"
        "    h.cancel()\n"
        '    print("joined {h.join()}")\n'
        "}\n"
    )


def w_cancel_then_join(body):
    return _worker(body) + (
        "\nfunc main() {\n"
        "    var g = TaskGroup()\n"
        "    let h = g.spawn(worker())\n"
        "    yield_now()\n"
        "    yield_now()\n"
        "    h.cancel()\n"
        '    print("joined {h.join()}")\n'
        "}\n"
    )


def w_panic_after_suspend(body):
    return (
        "func worker() -> Int {\n" + _indent(body, 4) + "\n"
        '    panic("corodiff teardown probe")\n'
        "}\n"
        "\nfunc main() {\n"
        "    var g = TaskGroup()\n"
        "    let h = g.spawn(worker())\n"
        '    print("joined {h.join()}")\n'
        "}\n"
    )


def w_unjoined_handle(body):
    return _worker(body) + (
        "\nfunc main() {\n"
        "    var g = TaskGroup()\n"
        "    let h = g.spawn(worker())\n"
        '    print("spawned, never joined")\n'
        "}\n"
    )


def w_group_teardown(body):
    return _worker(body) + (
        "\nfunc main() {\n"
        "    var g = TaskGroup()\n"
        "    let h1 = g.spawn(worker())\n"
        "    let h2 = g.spawn(worker())\n"
        '    print("spawned two, joined neither")\n'
        "}\n"
    )


def w_mt_spawn(body):
    # `TaskGroup(threads:)` allocates, so design 234 made it a fallible `init`
    # returning `Result<TaskGroup, AllocError>`; the bare spelling stopped
    # compiling and took every pair of this context with it (DF-284a's family,
    # at a WRAPPER rather than the prelude — which is what the dead-context
    # check below exists for).
    return _worker(body) + (
        "\nfunc main() {\n"
        "    var g = try! TaskGroup(threads: 2)\n"
        "    let h1 = g.spawn(worker())\n"
        "    let h2 = g.spawn(worker())\n"
        '    print("joined {h1.join()} {h2.join()}")\n'
        "}\n"
    )


# The generic-driven-function wrappers share this body: a generic suspending
# function carrying an abstract-`T` cell across the whole combo body, with the
# instantiation supplying a deinit witness so the exactly-once oracle can read
# that cell.
#
# WHY THE AXIS EXISTS. Every other context drives a CONCRETE frame. Sweep S1
# row p08c showed that a generic driven function's frame is judged by the
# post-transform re-check at its ABSTRACT form, where the tier is unknown and
# the permissive answer is the one that comes back (DF-217i). A frame-storage
# spelling that is wrong only at a concrete tier is therefore invisible to the
# concrete contexts' twin parity AND to the re-check — the generic drive is the
# one place both oracles are weak at once, so it gets its own axis value.
def _gworker(body):
    return (
        "func gworker<T>(seed: T) -> Int {\n" + _indent(body, 4) + "\n"
        f"    {CLOSED}\n"
        "    let _ = move seed\n"
        "    0\n"
        "}\n"
    )


def w_generic_spawn(body):
    return _gworker(body) + (
        "\nfunc main() {\n"
        "    var g = TaskGroup()\n"
        "    let h = g.spawn(gworker(mk_res(9)))\n"
        '    print("joined {h.join()}")\n'
        "}\n"
    )


def w_generic_ambient(body):
    return _gworker(body) + (
        "\nfunc main() {\n"
        '    print("returned {gworker(mk_res(9))}")\n'
        "}\n"
    )


def w_nested_generic_susp(body):
    """A CONCRETE driven root whose suspension travels through a nested call to
    an unconditionally-suspending GENERIC (DF-258a's shape).

    The other two generic contexts drive a generic ROOT; this one drives a plain
    one and puts the generic UNDER it, which is the position 218b's landing note
    (c) recorded as the hole in consumption symmetry: promotion declines for a
    template that suspends without calling a type-parameter method, so codegen's
    late monomorphization compiles the instantiation and the cooperative
    contract is dropped on the floor. The parity oracle does not see the missing
    park (the values still flow), and that is the point of the row: design 218
    unit 1.5 moves this instantiation onto the ordinary concrete path, and the
    ownership behaviour on either side of that move must be identical.
    """
    return _worker(body) + (
        "\nfunc main() {\n"
        "    var g = TaskGroup()\n"
        "    let h = g.spawn(worker())\n"
        '    print("joined {h.join()}")\n'
        "}\n"
    )


def nested_generic_hop(lines):
    """Prefix the body with the nested suspending-generic call.

    In the BODY rather than the wrapper, so `desuspend` rewrites it for the
    control twin — the twins must differ in exactly one thing, the suspension,
    and a wrapper is shared verbatim by both.
    """
    return ['let hopped = ghop_s<Int>(1)',
            'print("hop {hopped}")'] + list(lines)


def observe_cancel(lines):
    """Insert a cancellation observation point after the body's first suspend.

    The check goes into the BODY, not the wrapper, so the control twin keeps it
    too — the twins then differ in exactly one thing, the suspension, which is
    what the whole instrument rests on. A cancelled task that returns early
    still holds every binding made before the check, and each of those is a
    frame slot that must be released exactly once.
    """
    out = []
    inserted = False
    for line in lines:
        out.append(line)
        if not inserted and line.strip() == "yield_now()" and \
                len(line) - len(line.lstrip()) == 0:
            out.append("if cancelled() {")
            out.append('    print("cancel path")')
            out.append("    return 1")
            out.append("}")
            inserted = True
    if not inserted:
        # No top-level suspend to hang the check on (an `in_rhs` body suspends
        # inside an expression): observe at the end, where the bindings are all
        # still live.
        out.append("if cancelled() {")
        out.append('    print("cancel path")')
        out.append("    return 1")
        out.append("}")
    return out


CONTEXTS = [
    Context("susp_main", w_susp_main, full_cross=True),
    Context("taskgroup_spawn", w_taskgroup_spawn, full_cross=True,
            void_return="return 0"),
    Context("loop_second_iter", w_loop_second_iter, full_cross=True,
            oracle_class="loop"),
    Context("loop_for_inclusive", w_loop_for_inclusive, full_cross=True,
            oracle_class="loop",
            note="`for i in 1..=2` — the transform HAND-WRITES a driven range "
                 "loop's header and step out of frame slots, so unlike the "
                 "`while` context this exercises compiler-authored control "
                 "flow; DF-225m dropped the last iteration here"),
    Context("loop_for_inclusive_once", w_loop_for_inclusive_once,
            oracle_class="loop",
            note="`for i in 1..=1` — a single-iteration inclusive range, "
                 "DF-225m's loudest row: the driven body ran ZERO times"),
    Context("loop_for_exclusive", w_loop_for_exclusive, oracle_class="loop",
            note="`for i in 0..2` — the exclusive control beside the two "
                 "inclusive contexts, so a regression in the shared header/step "
                 "code is attributable to a range FLAVOUR, not to `for`"),
    Context("closure_from_driven", w_closure_from_driven, full_cross=True),
    Context("nested_block_tail", w_nested_block_tail),
    Context("method_driven", w_method_driven, has_self=True),
    Context("cancel_mid_suspend", w_cancel_mid_suspend, oracle_class="cancel",
            stdout_parity="off",
            void_return="return 0", body_transform=observe_cancel,
            note="a cancelled task takes a different path from its uncancelled "
                 "twin by design, so only the witness oracle applies"),
    Context("cancel_before_start", w_cancel_before_start, oracle_class="cancel",
            stdout_parity="off",
            void_return="return 0", body_transform=observe_cancel,
            note="cancelled before the task is ever polled"),
    Context("cancel_then_join", w_cancel_then_join, oracle_class="cancel",
            stdout_parity="off",
            void_return="return 0",
            note="cancelled with no observation point in the body — it runs to "
                 "completion, and teardown must be unaffected"),
    Context("panic_after_suspend", w_panic_after_suspend, oracle_class="panic",
            stdout_parity="off",
            leak_check=False, void_return="return 0",
            note="a panic ABORTS without unwinding, so nothing is released and "
                 "a leak means nothing here; the check that survives is that "
                 "no witness is released TWICE on the way down"),
    Context("unjoined_handle", w_unjoined_handle, oracle_class="teardown",
            stdout_parity="off",
            void_return="return 0",
            note="the handle is dropped without a join; the group's Deinit "
                 "drains the task"),
    Context("group_teardown", w_group_teardown, oracle_class="teardown",
            stdout_parity="off",
            void_return="return 0",
            note="two unjoined tasks — teardown ORDER is unspecified, so the "
                 "oracle is the released SET, not the sequence"),
    Context("mt_spawn", w_mt_spawn, oracle_class="mt", stdout_parity="off",
            void_return="return 0",
            excludes=("closure_capture_implicit", "closure_capture_move",
                      "closure_capture_self"),
            note="TaskGroup(threads: 2): two workers interleave INSIDE a line "
                 "(`scope closedNEW t1` is real output), so no comparison of "
                 "stdout is meaningful here — the witness counts, which are "
                 "read out of the text rather than off line boundaries, are"),
    Context("generic_spawn", w_generic_spawn, oracle_class="generic",
            void_return="return 0",
            note="a GENERIC driven function, spawned, instantiated at the "
                 "NoCopy witness — sweep S1 row p08c's shape: the frame holds "
                 "an abstract-T cell the post-transform re-check judges "
                 "permissively (DF-217i), so the twin parity is the only "
                 "oracle on it"),
    Context("generic_ambient", w_generic_ambient, oracle_class="generic",
            void_return="return 0",
            note="the same generic driven function reached through the "
                 "AMBIENT entry executor instead of spawn — the other of the "
                 "two ways a generic frame gets driven"),
    Context("nested_generic_susp", w_nested_generic_susp,
            oracle_class="generic", void_return="return 0",
            body_transform=nested_generic_hop,
            note="a CONCRETE driven root calling a nested unconditionally-"
                 "suspending generic (DF-258a) — the instantiation the "
                 "transform declines to promote and codegen builds late, "
                 "which design 218 unit 1.5 moves onto the ordinary path"),
]

CONTEXT_BY_NAME = {c.name: c for c in CONTEXTS}


# ---------------------------------------------------------------------------
# Program construction.
# ---------------------------------------------------------------------------

SUSP_CALL_RE = re.compile(r"\bmk_(triv|bag|tag|vec|res)_s\(")
# The generic hop's twin rewrite. Separate from `SUSP_CALL_RE` because the call
# carries an explicit type argument (`ghop_s<Int>(`), so the `_s` is not
# followed by the open paren the maker pattern anchors on.
GHOP_CALL_RE = re.compile(r"\bghop_s<")


def desuspend(lines):
    """The CONTROL twin's body: the same value flow with no suspension.

    Derived from the driven body mechanically — drop the `yield_now()`
    statements, rewrite each suspending maker to its sync sibling — so the two
    twins cannot drift apart, and so the MINIMIZER can shrink the driven body
    and get a matching control for free.
    """
    out = []
    for line in lines:
        if line.strip() == "yield_now()":
            continue
        line = SUSP_CALL_RE.sub(lambda m: f"mk_{m.group(1)}(", line)
        out.append(GHOP_CALL_RE.sub("ghop<", line))
    return out


class Combo:
    def __init__(self, binding, tier, placement, context):
        self.binding = binding
        self.tier = tier
        self.placement = placement
        self.context = context

    @property
    def tag(self):
        return f"{self.binding}__{self.tier}__{self.placement}__{self.context}"

    def __repr__(self):
        return f"<Combo {self.tag}>"


def build_bodies(combo):
    """Return `(driven_lines, control_lines, prune_reason)`."""
    ctx = CONTEXT_BY_NAME[combo.context]
    tier = TIER_BY_NAME[combo.tier]
    builder = BINDING_BY_NAME[combo.binding]
    if combo.binding in ctx.excludes:
        return None, None, (f"{combo.binding}: excluded from {ctx.name} "
                            f"({ctx.note or 'context restriction'})")
    lines, reason = builder(tier, combo.placement, ctx)
    if lines is None:
        return None, None, reason
    if ctx.body_transform is not None:
        lines = ctx.body_transform(lines)
    return lines, desuspend(lines), None


def build_source(combo, body_lines):
    return PRELUDE + "\n" + CONTEXT_BY_NAME[combo.context].wrap(body_lines)


def all_combos():
    """The whole cross, in a stable order, with the pruning rules applied."""
    out, pruned = [], []
    for (bname, _), tier, placement, ctx in itertools.product(
            BINDINGS, TIERS, PLACEMENTS, CONTEXTS):
        if not ctx.full_cross:
            if bname not in CURATED_BINDINGS and not (
                    bname == "closure_capture_self" and ctx.has_self):
                pruned.append((f"{bname}__{tier.name}__{placement}__{ctx.name}",
                               "context runs the curated binding subset"))
                continue
            if tier.name not in CURATED_TIERS:
                pruned.append((f"{bname}__{tier.name}__{placement}__{ctx.name}",
                               "context runs the curated (witnessing) tiers"))
                continue
            if placement not in CURATED_PLACEMENTS:
                pruned.append((f"{bname}__{tier.name}__{placement}__{ctx.name}",
                               "context runs the curated placements"))
                continue
        elif bname == "closure_capture_self":
            pruned.append((f"{bname}__{tier.name}__{placement}__{ctx.name}",
                           "closure_capture_self needs a method context"))
            continue
        out.append(Combo(bname, tier.name, placement, ctx.name))
    return out, pruned


def stratified_sample(combos, count, seed):
    """`count` combos covering every value of every axis, as a function of seed.

    A random sample of a four-axis cross reliably misses whole axis values,
    which is how a lane ends up green because it never generated the shape that
    breaks. This covers first and fills after.
    """
    rng = random.Random(seed * 2654435761 % (2 ** 61 - 1))
    pool = list(combos)
    rng.shuffle(pool)

    wanted = []
    for axis in ("context", "binding", "tier", "placement"):
        seen = set()
        for c in combos:
            seen.add(getattr(c, axis))
        wanted += [(axis, v) for v in sorted(seen)]

    chosen, chosen_tags = [], set()
    covered = set()
    for axis, value in wanted:
        if (axis, value) in covered:
            continue
        for c in pool:
            if getattr(c, axis) != value or c.tag in chosen_tags:
                continue
            chosen.append(c)
            chosen_tags.add(c.tag)
            for a in ("context", "binding", "tier", "placement"):
                covered.add((a, getattr(c, a)))
            break
    for c in pool:
        if len(chosen) >= count:
            break
        if c.tag not in chosen_tags:
            chosen.append(c)
            chosen_tags.add(c.tag)
    # Report in the cross's own order so a run reads like the axis table.
    order = {c.tag: i for i, c in enumerate(combos)}
    chosen.sort(key=lambda c: order[c.tag])
    return chosen


# ---------------------------------------------------------------------------
# The oracle.
# ---------------------------------------------------------------------------

# NOT line-anchored, deliberately. Two threads of an MT group interleave INSIDE
# a line — real output from this harness contains `scope closedNEW t1` — so a
# per-line reader loses a witness and then reports the missing creation as a
# double free. The ids the prelude mints are `r1`/`t1`/`dr1`/`dt1`, so a
# restricted charset is enough to pick them back out of a torn line.
WITNESS_NEW_RE = re.compile(r"NEW ([a-z]+[0-9]+)")
WITNESS_DEL_RE = re.compile(r"DEINIT ([a-z]+[0-9]+)")
# A deinit whose name renders EMPTY ran over storage that no longer holds a
# live value — the husk a second release reads. DF-217h's own tracker entry
# describes exactly this face of it.
WITNESS_HUSK_RE = re.compile(r"DEINIT *$", re.MULTILINE)


def witness_counts(stdout):
    made, freed = {}, {}
    for wid in WITNESS_NEW_RE.findall(stdout):
        made[wid] = made.get(wid, 0) + 1
    for wid in WITNESS_DEL_RE.findall(stdout):
        freed[wid] = freed.get(wid, 0) + 1
    return made, freed, len(WITNESS_HUSK_RE.findall(stdout))


class Outcome:
    """One twin's whole story: how it compiled, and how it ran."""

    def __init__(self):
        self.compile_rc = None
        self.compile_out = ""
        self.compile_timed_out = False
        self.run_rc = None
        self.run_out = ""
        self.run_err = ""
        self.run_timed_out = False

    @property
    def compiled(self):
        return self.compile_rc == 0

    @property
    def has_ice(self):
        return (ICE_MARK in self.compile_out
                or TRACEBACK_MARK in self.compile_out)

    def summary(self):
        if self.compile_timed_out:
            return "compile HUNG"
        if not self.compiled:
            first = next((l for l in self.compile_out.splitlines()
                          if "error:" in l or ICE_MARK in l), "")
            return f"refused (rc={self.compile_rc}): {first.strip()[:160]}"
        if self.run_timed_out:
            return "run HUNG"
        return (f"ran rc={self.run_rc}, stdout="
                f"{self.run_out!r}"[:400])


class Finding:
    def __init__(self, kind, combo, detail, diagnostic=""):
        self.kind = kind
        self.combo = combo
        self.detail = detail
        self.diagnostic = diagnostic

    @property
    def signature(self):
        """A stable key for ONE bug, so a family reported from thirty combos
        reads as one ledger line.

        A compiler complaint IS its own identity, so a diagnostic keys itself —
        the same refusal found at another tier or from another binding matches.
        A runtime finding has no message, so its identity is the CONSTRUCT and
        the class of context it broke in: the tier and the particular context
        drop out (DF-217h double-frees at every tier and in every linear
        context), the oracle class stays (a loop-only drift is a different bug
        from the same construct misbehaving in straight-line code).
        """
        if self.diagnostic:
            return f"{self.kind}: {normalize_diagnostic(self.diagnostic)}"
        cls = CONTEXT_BY_NAME[self.combo.context].oracle_class
        return (f"{self.kind}: {self.combo.binding}/{self.combo.placement}"
                f" @ {cls}")


HELPER_RE = re.compile(r"\bmk_(?:triv|bag|tag|vec|res)(?:_s|_opt)?\b")
DERIVE_RE = re.compile(r"\bderive_(?:triv|bag|tag|vec|res)\b")
WRAPENUM_RE = re.compile(r"\bWrap_(?:Trivial|Implicit|Tag|Explicit|Nocopy)\b")


def normalize_diagnostic(text):
    """A stable key for ONE compiler complaint, whatever combo reached it.

    Everything combo-specific is normalized away — the source path, every line
    and column, the generated helper and enum names, the tier's own type — so a
    ledger entry written once matches the same bug found at another tier, in
    another context, from another binding.
    """
    lines = [ANSI_RE.sub("", l).strip() for l in text.splitlines() if l.strip()]
    detail = ""
    anchor = next((i for i, l in enumerate(lines) if ICE_MARK in l), None)
    if anchor is not None:
        detail = lines[anchor]
    else:
        detail = next((l for l in lines if l.startswith("error:")
                       or ": error:" in l), lines[0] if lines else "")
    detail = re.sub(r"[^\s:]*[/\\][^\s:]*\.saw", "<src>", detail)
    detail = HELPER_RE.sub("<mk>", detail)
    detail = DERIVE_RE.sub("<derive>", detail)
    detail = WRAPENUM_RE.sub("<wrap>", detail)
    detail = re.sub(r"`[^`]*`", "`X`", detail)
    detail = re.sub(r"\d+", "N", detail)
    return detail[:220]


def judge(combo, driven, control):
    """Apply the four checks, in order. Returns a list of Findings."""
    ctx = CONTEXT_BY_NAME[combo.context]
    out = []

    # 1. The compiler misbehaving is a finding on either twin, parity or not.
    for who, o in (("driven", driven), ("control", control)):
        if o.compile_timed_out:
            out.append(Finding("COMPILE-HANG", combo,
                               f"{who} twin: the compiler did not finish"))
        elif o.has_ice:
            out.append(Finding("ICE", combo, f"{who} twin", o.compile_out))
    if out:
        return out

    # 2. Compile parity.
    if driven.compiled != control.compiled:
        if not driven.compiled:
            out.append(Finding("BOGUS-REFUSAL", combo,
                               "the driven twin is refused where its "
                               "non-suspending twin compiles",
                               driven.compile_out))
        else:
            out.append(Finding("BOGUS-ACCEPT", combo,
                               "the non-suspending twin is refused where the "
                               "driven one compiles", control.compile_out))
        return out
    if not driven.compiled:
        return out          # both refuse identically — a deliberate rule

    # 3. Run parity.
    for who, o in (("driven", driven), ("control", control)):
        if o.run_timed_out:
            out.append(Finding("RUN-HANG", combo, f"{who} twin hung"))
    if out:
        return out

    if driven.run_rc != control.run_rc:
        out.append(Finding("WRONG-EXIT", combo,
                           f"driven rc={driven.run_rc} control rc={control.run_rc}"))
    elif ctx.stdout_parity != "off":
        d, c = driven.run_out, control.run_out
        if ctx.stdout_parity == "sorted":
            d = "\n".join(sorted(d.splitlines()))
            c = "\n".join(sorted(c.splitlines()))
        if d != c:
            # Two very different bugs wear this one face. When the twins print
            # the same LINES in a different ORDER, nothing was lost or
            # duplicated and what moved is a destruction POINT — a resource
            # held past the scope that owned it. When the multisets differ, a
            # value was created or destroyed that the twin did not.
            same_multiset = sorted(d.splitlines()) == sorted(c.splitlines())
            kind = "DEINIT-ORDER" if same_multiset else "STDOUT-PARITY"
            out.append(Finding(kind, combo,
                               f"driven={driven.run_out!r}\n"
                               f"control={control.run_out!r}"))

    # 4. Witness exactly-once, per twin, whatever parity said.
    for who, o in (("driven", driven), ("control", control)):
        made, freed, husks = witness_counts(o.run_out)
        if husks:
            out.append(Finding("HUSK-RELEASE", combo,
                               f"{who} twin: {husks} deinit(s) ran over storage "
                               f"holding no live value (the name renders empty)"
                               f"\nstdout={o.run_out!r}"))
        for wid in sorted(set(made) | set(freed)):
            n_made, n_freed = made.get(wid, 0), freed.get(wid, 0)
            if n_freed > n_made:
                out.append(Finding("DOUBLE-FREE", combo,
                                   f"{who} twin: `{wid}` created {n_made}x, "
                                   f"destroyed {n_freed}x\n"
                                   f"stdout={o.run_out!r}"))
            elif n_freed < n_made and ctx.leak_check:
                out.append(Finding("LEAK", combo,
                                   f"{who} twin: `{wid}` created {n_made}x, "
                                   f"destroyed {n_freed}x\n"
                                   f"stdout={o.run_out!r}"))
    return out


# ---------------------------------------------------------------------------
# Running things. Wave-bounded, always.
# ---------------------------------------------------------------------------

class Runner:
    def __init__(self, python, sawc, compile_timeout, run_timeout):
        self.python = python
        self.sawc = sawc
        self.compile_timeout = compile_timeout
        self.run_timeout = run_timeout

    def compile_command(self, src, out):
        return [self.python, self.sawc, src, "-o", out]

    def start_compile(self, src, out):
        return subprocess.Popen(self.compile_command(src, out),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, cwd=REPO)

    def start_run(self, binary):
        try:
            return subprocess.Popen([binary], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, cwd=REPO)
        except OSError:
            return None          # the compile reported success but linked nothing

    @staticmethod
    def reap(proc, deadline):
        remaining = max(0.1, deadline - time.monotonic())
        try:
            out, err = proc.communicate(timeout=remaining)
            out = ANSI_RE.sub("", out or "")
            return proc.returncode, out, (err or ""), False
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            return None, ANSI_RE.sub("", out or ""), (err or ""), True


def evaluate_pairs(runner, combos, work_dir, jobs, progress=None):
    """Build, compile, run and judge `combos`, `jobs`-wide, wave by wave.

    Yields `(combo, driven, control, findings)` per pair, and
    `(combo, None, None, [prune_reason])` for a combo the axes prune.
    """
    os.makedirs(work_dir, exist_ok=True)
    pairs_per_wave = max(1, jobs // 2)
    batch = []
    done = 0

    def flush(batch):
        # Write, compile, run, judge — each phase fully reaped before the next.
        for slot, item in enumerate(batch):
            item["slot"] = slot
            for who in ("driven", "control"):
                path = os.path.join(work_dir, f"w{slot}__{who}.saw")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(item[who + "_src"])
                item[who + "_path"] = path
                item[who + "_bin"] = os.path.join(work_dir, f"w{slot}__{who}")
                item[who] = Outcome()

        deadline = time.monotonic() + runner.compile_timeout
        procs = []
        for item in batch:
            for who in ("driven", "control"):
                procs.append((item, who, runner.start_compile(
                    item[who + "_path"], item[who + "_bin"])))
        for item, who, proc in procs:
            rc, out, _err, to = runner.reap(proc, deadline)
            o = item[who]
            o.compile_rc, o.compile_out, o.compile_timed_out = rc, out, to

        deadline = time.monotonic() + runner.run_timeout
        procs = []
        for item in batch:
            for who in ("driven", "control"):
                if item[who].compiled and os.path.exists(item[who + "_bin"]):
                    proc = runner.start_run(item[who + "_bin"])
                    if proc is not None:
                        procs.append((item, who, proc))
        for item, who, proc in procs:
            rc, out, err, to = runner.reap(proc, deadline)
            o = item[who]
            o.run_rc, o.run_out, o.run_err, o.run_timed_out = rc, out, err, to

        for item in batch:
            yield (item["combo"], item["driven"], item["control"],
                   judge(item["combo"], item["driven"], item["control"]))

    for combo in combos:
        driven_lines, control_lines, reason = build_bodies(combo)
        if driven_lines is None:
            yield (combo, None, None, reason)
            continue
        batch.append({
            "combo": combo,
            "driven_src": build_source(combo, driven_lines),
            "control_src": build_source(combo, control_lines),
            "driven_lines": driven_lines,
        })
        if len(batch) >= pairs_per_wave:
            for result in flush(batch):
                done += 1
                yield result
            batch = []
            if progress:
                progress(done)
    if batch:
        for result in flush(batch):
            done += 1
            yield result
        if progress:
            progress(done)


def evaluate_one(runner, combo, driven_lines, work_dir, prefix="probe"):
    """One pair, synchronously. Used by the minimizer and by --replay."""
    os.makedirs(work_dir, exist_ok=True)
    control_lines = desuspend(driven_lines)
    outcomes = {}
    for who, lines in (("driven", driven_lines), ("control", control_lines)):
        src = build_source(combo, lines)
        path = os.path.join(work_dir, f"{prefix}__{who}.saw")
        binary = os.path.join(work_dir, f"{prefix}__{who}")
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
        o = Outcome()
        proc = runner.start_compile(path, binary)
        o.compile_rc, o.compile_out, _e, o.compile_timed_out = runner.reap(
            proc, time.monotonic() + runner.compile_timeout)
        if o.compiled and os.path.exists(binary):
            proc = runner.start_run(binary)
            if proc is not None:
                o.run_rc, o.run_out, o.run_err, o.run_timed_out = runner.reap(
                    proc, time.monotonic() + runner.run_timeout)
        outcomes[who] = o
        outcomes[who + "_src"] = src
    findings = judge(combo, outcomes["driven"], outcomes["control"])
    return outcomes, findings


def minimize(runner, combo, driven_lines, kind, work_dir, budget=24):
    """Shrink the driven body while the finding stays the same KIND.

    The CONTROL twin is re-derived from each candidate, so the reduction keeps
    the twin relationship intact — a minimized parity finding is still a parity
    finding, not a driven program that happens to crash.
    """
    lines = list(driven_lines)
    spent = 0

    def still_fails(candidate):
        nonlocal spent
        spent += 1
        _o, findings = evaluate_one(runner, combo, candidate, work_dir, "min")
        return any(f.kind == kind for f in findings)

    chunk = max(1, len(lines) // 2)
    while chunk >= 1 and spent < budget:
        i, changed = 0, False
        while i < len(lines) and spent < budget:
            candidate = lines[:i] + lines[i + chunk:]
            if candidate and still_fails(candidate):
                lines, changed = candidate, True
            else:
                i += chunk
        if not changed:
            if chunk == 1:
                break
            chunk //= 2
    return lines, spent


# ---------------------------------------------------------------------------
# The known-findings ledger.
# ---------------------------------------------------------------------------

def load_known(path):
    known = {}
    if not os.path.exists(path):
        return known
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            df, _, sig = line.partition("\t")
            if sig.strip():
                known[sig.strip()] = df.strip()
    return known


# ---------------------------------------------------------------------------
# The driver.
# ---------------------------------------------------------------------------

def report_text(finding, combo, driven, control, driven_src, control_src,
                minimized_src):
    ctx = CONTEXT_BY_NAME[combo.context]
    parts = [
        "corodiff finding",
        "================",
        f"kind:       {finding.kind}",
        f"signature:  {finding.signature}",
        f"combo:      {combo.tag}",
        f"  binding:   {combo.binding}",
        f"  tier:      {combo.tier}",
        f"  placement: {combo.placement}",
        f"  context:   {combo.context}",
        f"oracle:     class={ctx.oracle_class}, "
        f"stdout-parity={ctx.stdout_parity}, "
        f"leak-check={'on' if ctx.leak_check else 'off'}"
        + (f" ({ctx.note})" if ctx.note else ""),
        f"replay:     tools/corodiff.py --replay {combo.tag}",
        "",
        "--- what differs ---",
        finding.detail,
        "",
        f"--- driven twin --- {driven.summary() if driven else 'n/a'}",
        driven_src,
        f"--- control twin --- {control.summary() if control else 'n/a'}",
        control_src,
    ]
    if minimized_src is not None:
        parts += ["--- minimized driven twin ---", minimized_src]
    if driven is not None and driven.compile_out.strip():
        parts += ["--- driven compiler output ---", driven.compile_out]
    if control is not None and control.compile_out.strip():
        parts += ["--- control compiler output ---", control.compile_out]
    return "\n".join(parts) + "\n"


def check_prelude(runner, work_dir):
    """THE COMPILE FLOOR: the shared prelude must compile, on its own.

    Check 2 exempts a pair whose twins refuse IDENTICALLY, because a shape the
    language refuses is not a transform bug. That exemption cannot tell "the
    language refuses this shape" from "the harness's own declarations stopped
    compiling", and the corpus is GENERATED, so nothing else in the tree ever
    compiles these lines — a prelude that goes stale takes the whole lane down
    and scores it clean. It has happened TWICE: design 219 wave B's rename
    (found by hand), and design 234's fallible `Arc(value:)`, which left every
    one of the 2408 combos refusing on both twins with the battery green
    (DF-284a). This is the assertion the exemption was missing: it fails the
    run, loudly, before a single combo is judged.

    Deliberately the PRELUDE alone — a body error belongs to its combo and is
    the instrument working. Type errors in the prelude's own bodies fire
    whether or not anything calls them, so an empty `main` is enough.
    """
    os.makedirs(work_dir, exist_ok=True)
    path = os.path.join(work_dir, "prelude_floor.saw")
    binary = os.path.join(work_dir, "prelude_floor")
    with open(path, "w", encoding="utf-8") as f:
        f.write(PRELUDE + "\nfunc main() { }\n")
    proc = runner.start_compile(path, binary)
    rc, out, _err, timed_out = runner.reap(
        proc, time.monotonic() + runner.compile_timeout)
    if timed_out:
        return False, "the prelude compile TIMED OUT"
    if rc != 0:
        return False, out
    return True, ""


def run(args):
    combos, pruned_by_axes = all_combos()
    if args.filter:
        combos = [c for c in combos if args.filter in c.tag]
        if not combos:
            print(f"corodiff: no combo matches `{args.filter}`", file=sys.stderr)
            return 2
    if args.count is not None:
        combos = stratified_sample(combos, args.count, args.seed)

    runner = Runner(sys.executable, args.sawc, args.compile_timeout,
                    args.run_timeout)
    ok, why = check_prelude(runner, WORK_DIR)
    if not ok:
        print("corodiff: THE PRELUDE DOES NOT COMPILE — every generated pair "
              "would refuse on both twins and be scored clean. Repair the "
              "shared declarations before reading anything else.",
              file=sys.stderr)
        print(why, file=sys.stderr)
        return 2
    known = {} if args.ignore_known else load_known(args.known)
    known_hits = {}
    seen_signatures = {}
    prune_reasons = {}
    counters = dict(pairs=0, pruned=0, compiled_ok=0, refused=0,
                    both_refused=0, matched=0)
    # THE DEAD-CONTEXT CHECK, the compile floor's per-context half. `pairs` and
    # `both_refused` per context name: a context every one of whose pairs
    # refused on BOTH twins is testing nothing, and check 2's identical-refusal
    # exemption scores it clean. This is the prelude floor's blind spot moved
    # one level down — a WRAPPER that stops compiling takes only its own rows,
    # so the floor cannot see it — and it is not hypothetical: design 234's
    # fallible `TaskGroup(threads:)` killed `mt_spawn`, and `nested_block_tail`
    # was written around `{ ... }()`, a spelling that has never parsed
    # (DF-284b). Both were found by reading run summaries by hand.
    per_context = {}
    new_findings = 0
    started = time.monotonic()

    mode = ("the whole cross" if args.count is None
            else f"{len(combos)} pair(s), stratified from seed {args.seed}")
    print(f"corodiff: {mode}; {len(combos)} to run, waves of {args.jobs}")

    every = 50 if args.count is None else 20

    def progress(done):
        if done % every == 0:
            print(f"  ... {done}/{len(combos)} pairs, {new_findings} new "
                  f"finding(s), {time.monotonic() - started:.0f}s")

    for combo, driven, control, result in evaluate_pairs(
            runner, combos, WORK_DIR, args.jobs, progress):
        if driven is None:
            counters["pruned"] += 1
            prune_reasons[result] = prune_reasons.get(result, 0) + 1
            continue
        counters["pairs"] += 1
        seen_ctx = per_context.setdefault(combo.context, [0, 0])
        seen_ctx[0] += 1
        if driven.compiled and control.compiled:
            counters["compiled_ok"] += 1
        elif not driven.compiled and not control.compiled:
            counters["both_refused"] += 1
            seen_ctx[1] += 1
        else:
            counters["refused"] += 1
        if not result:
            counters["matched"] += 1
            continue

        for finding in result:
            sig = finding.signature
            if sig in known:
                known_hits.setdefault(sig, []).append(combo.tag)
                continue
            if sig in seen_signatures:
                seen_signatures[sig]["count"] += 1
                continue
            driven_lines, control_lines, _ = build_bodies(combo)
            minimized_src = None
            if not args.no_minimize:
                small, spent = minimize(runner, combo, driven_lines,
                                        finding.kind, WORK_DIR)
                if len(small) < len(driven_lines):
                    minimized_src = build_source(combo, small)
                    finding.detail += (f"\n(minimized to {len(small)} of "
                                       f"{len(driven_lines)} body lines in "
                                       f"{spent} probe(s))")
            os.makedirs(args.findings, exist_ok=True)
            stem = f"{finding.kind.lower()}__{combo.tag}"
            base = os.path.join(args.findings, stem)
            with open(base + "__driven.saw", "w", encoding="utf-8") as f:
                f.write(build_source(combo, driven_lines))
            with open(base + "__control.saw", "w", encoding="utf-8") as f:
                f.write(build_source(combo, control_lines))
            with open(base + ".txt", "w", encoding="utf-8") as f:
                f.write(report_text(finding, combo, driven, control,
                                    build_source(combo, driven_lines),
                                    build_source(combo, control_lines),
                                    minimized_src))
            seen_signatures[sig] = {"count": 1, "stem": stem}
            new_findings += 1
            print(f"  FINDING [{finding.kind}] {combo.tag}")
            print(f"           {sig}")

    elapsed = time.monotonic() - started
    print()
    if prune_reasons:
        total = sum(prune_reasons.values())
        print(f"corodiff: {total} combo(s) pruned, by reason:")
        for reason, n in sorted(prune_reasons.items(), key=lambda kv: -kv[1]):
            print(f"  {n:5d}  {reason}")
    for sig, tags in sorted(known_hits.items()):
        print(f"  known [{known[sig]}] x{len(tags)}  {sig}")
        print(f"           first: {tags[0]}")
    print(f"corodiff: {counters['pairs']} pair(s) in {elapsed:.1f}s — "
          f"{counters['matched']} clean, {counters['compiled_ok']} compiled on "
          f"both twins, {counters['both_refused']} refused identically, "
          f"{counters['refused']} refused on one twin, "
          f"{counters['pruned']} pruned, "
          f"{sum(len(v) for v in known_hits.values())} known hit(s), "
          f"{new_findings} NEW finding(s)")
    dead = sorted(name for name, (ran, refused) in per_context.items()
                  if ran and ran == refused)
    if dead:
        print("\ncorodiff: DEAD CONTEXT(S) — every pair refused on BOTH twins, "
              "so these rows\ntest nothing and check 2 scored them clean. "
              "Repair the wrapper:", file=sys.stderr)
        for name in dead:
            print(f"  {name}  ({per_context[name][0]} pair(s), all refused)",
                  file=sys.stderr)
        print("  replay one to see the compiler's own words: "
              "corodiff.py --replay <tag>", file=sys.stderr)

    if seen_signatures:
        print(f"\nWritten to {os.path.relpath(args.findings, REPO)}:")
        for sig, info in seen_signatures.items():
            print(f"  {info['stem']}  x{info['count']}  {sig}")
        print("\nEach is a DF: file it, pin the repro in examples/ under a "
              "behavior name,\nXFAIL it citing the DF, and add the signature "
              "to tools/corodiff_known.txt.")
        return 1
    return 1 if dead else 0


def replay(args):
    combos, _ = all_combos()
    match = next((c for c in combos if c.tag == args.replay), None)
    if match is None:
        near = [c.tag for c in combos if args.replay in c.tag][:10]
        print(f"corodiff: no combo tagged `{args.replay}`", file=sys.stderr)
        if near:
            print("did you mean:\n  " + "\n  ".join(near), file=sys.stderr)
        return 2
    driven_lines, control_lines, reason = build_bodies(match)
    if driven_lines is None:
        print(f"corodiff: {match.tag} is PRUNED — {reason}")
        return 2
    runner = Runner(sys.executable, args.sawc, args.compile_timeout,
                    args.run_timeout)
    outcomes, findings = evaluate_one(runner, match, driven_lines, WORK_DIR,
                                      "replay")
    ctx = CONTEXT_BY_NAME[match.context]
    print(f"combo:   {match.tag}")
    print(f"oracle:  stdout-parity={ctx.stdout_parity}, "
          f"leak-check={'on' if ctx.leak_check else 'off'}")
    if ctx.note:
        print(f"         {ctx.note}")
    for who in ("driven", "control"):
        print(f"\n--- {who} ---\n{outcomes[who + '_src']}")
        print(f"verdict: {outcomes[who].summary()}")
        if outcomes[who].compile_out.strip():
            print(outcomes[who].compile_out)
    print()
    if not findings:
        print("verdict: the twins AGREE — clean")
        return 0
    for f in findings:
        print(f"FINDING [{f.kind}] {f.signature}\n{f.detail}")
    return 1


def list_axes():
    print("BINDINGS (%d)" % len(BINDINGS))
    for name, _ in BINDINGS:
        print(f"  {name}")
    print("\nTIERS (%d)" % len(TIERS))
    for t in TIERS:
        mark = "witnessing" if t.witnesses else "parity only"
        print(f"  {t.name:<10} {t.saw_type:<14} {mark}")
    print("\nPLACEMENTS (%d)" % len(PLACEMENTS))
    print("  " + ", ".join(PLACEMENTS))
    print("\nCONTEXTS (%d)" % len(CONTEXTS))
    for c in CONTEXTS:
        scope = "FULL CROSS" if c.full_cross else "curated subset"
        print(f"  {c.name:<22} {scope:<15} class={c.oracle_class:<9} "
              f"stdout={c.stdout_parity} "
              f"leak={'on' if c.leak_check else 'off'}")
        if c.note:
            print(f"      {c.note}")
    combos, pruned = all_combos()
    print(f"\n{len(combos)} combo(s) in the cross, {len(pruned)} pruned by the "
          f"axis rules")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--quick", nargs="?", type=int, const=60, metavar="N",
                      help="N stratified pairs covering every axis value "
                           "(default 60) — the battery mode")
    mode.add_argument("--all", action="store_true",
                      help="the whole cross (tens of minutes)")
    mode.add_argument("--replay", metavar="TAG",
                      help="rebuild ONE combo and print both twins in full")
    mode.add_argument("--list-axes", action="store_true",
                      help="print the axis grammar and the combo count")
    ap.add_argument("--seed", type=int, default=1,
                    help="the only source of variation in --quick's sample")
    ap.add_argument("--jobs", type=int, default=min(8, (os.cpu_count() or 4)),
                    help="wave width — processes alive at once; every wave is "
                         "reaped before the next")
    ap.add_argument("--filter", metavar="SUBSTRING",
                    help="only combos whose tag contains SUBSTRING")
    ap.add_argument("--findings", default=DEFAULT_FINDINGS,
                    help="where findings are written "
                         "(default .build/corodiff-findings/)")
    ap.add_argument("--sawc", default=DEFAULT_SAWC,
                    help="the sawc.py under test (default this tree's)")
    ap.add_argument("--known", default=KNOWN_FILE,
                    help="the XFAIL ledger of filed-but-unfixed signatures")
    ap.add_argument("--ignore-known", action="store_true",
                    help="report the ledger's entries as new — how you check "
                         "whether a filed one is fixed")
    ap.add_argument("--no-minimize", action="store_true",
                    help="skip delta-debugging a new finding's body")
    ap.add_argument("--compile-timeout", type=float, default=120.0,
                    help="per-WAVE compile seconds; exceeding it is a finding")
    ap.add_argument("--run-timeout", type=float, default=10.0,
                    help="per-WAVE run seconds; exceeding it is a HANG finding")
    ap.add_argument("--clean", action="store_true",
                    help="empty the findings directory first")
    ap.add_argument("--keep-work", action="store_true",
                    help="keep this run's scratch directory "
                         "(.build/corodiff-work/<pid>/) instead of removing it")
    args = ap.parse_args()

    if args.list_axes:
        return list_axes()
    if args.clean and os.path.isdir(args.findings):
        shutil.rmtree(args.findings)
    try:
        if args.replay:
            return replay(args)
        args.count = None if args.all else (args.quick if args.quick else 60)
        return run(args)
    finally:
        if not args.keep_work:
            shutil.rmtree(WORK_DIR, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

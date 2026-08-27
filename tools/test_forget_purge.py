#!/usr/bin/env python3
"""Design 218 stage 4's CITATION GATE: the trusted residue of the Slot
migration is auditable, or the build fails.

Two patterns, one rule. The migration replaced a hand-kept ownership discipline
with a checked one, and what it could not migrate — the deferred census families
— keeps that discipline alive at a NAMED set of sites. Every one of those sites
says which deferral keeps it there; a site that cannot name one is either a bug
or a migration nobody finished, and both are findings.

`__saw_forget(<optional place>)` clears an optional field's None/Some tag —
design 44's drop flag — WITHOUT reading the payload. It is correct only when it
is paired with exactly one prior consuming read, and the pairing lives in two
statements that any emission site can get wrong. Three did: DF-206f and DF-210f
were missing forgets (double release), DF-217h was a consuming read with no
forget at all, nine positions' worth.

`Slot.take()` is the read and the tag clear in ONE method body, so on a MIGRATED
frame field the state "consumed but still flagged live" is not representable.
218a section 9 wrote stage 4's exit criterion as "`__saw_forget` emission count
hits ZERO in the transform (grep-gated)", which pre-dates the deferred census
families stages 1-3 measured: `opt_closure`, address-taken locals, `Void`, fixed
arrays and DF-218h's window-move keep the legacy encoding, and a legacy encoding
is exactly a field that still owes its forget. (Two of the original set have
since retired into the migration: DF-218i's rendering operand, and design 247's
scrutinee-temp rows.)

So the criterion this gate enforces is the adapted one:

  1. `sawc/` spells `__saw_forget` in exactly ONE emission site, the funnel
     `_forget_call` in `sawc/coro_transform.py`. Every other spelling belongs to
     a CONSUMER — the builtin's registration, its typecheck, its lowering — and
     those files are listed below with what they do.
  2. Every call to that funnel CITES a deferred family. The citation is a real
     argument, not a comment: `_forget_call(place, family)` refuses a family
     that is not one of `DEFERRED_FAMILIES`, and `_forget_stmt` refuses a field
     that no family holds back (a migrated field's forget would be the DF-217h
     mispairing, so emitting one is a compiler bug and raises).
  3. The family set is the documented one. Adding a name here is a design
     decision — a new deferral — and it needs this file in the diff.

THE MARK STAMPS (M1/M3) ARE THE SECOND PATTERN, added by the lead's stage-4
contract extension. `frame_place_read` (M1) tells the transfer checkpoint that
ownership is already settled here and it must look away; `frame_owning_read`
(M3) asks codegen for a retain the checker never saw. Both are the transform
asserting an answer instead of letting the language give one — the exact thing
`Slot` retired — and 218a section 6 has them deleting when the last emitter
goes. Until then they are trusted residue, and the same rule applies:

  4. Every site that STAMPS M1 or M3 carries a `DEFERRED:` comment naming the
     family that keeps it alive, within
     CITATION_LOOKBACK lines above it or on the line itself. A stamp reached on
     a MIGRATED path has no family to name, which is how this gate reports one.
  5. Only the transform stamps them. The consumer-side skip and retain rules
     (the transfer checkpoint's, codegen's) are the other half of the same
     mechanism and delete with the emitters, per 218a section 6 — they are not
     required to cite anything.

Run from the repo root:  ./.venv/bin/python tools/test_forget_purge.py
Exit code 0 = pass; nonzero (naming each uncited site) = fail.
"""
import ast
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAWC = os.path.join(REPO, "sawc")

TRANSFORM = os.path.join(SAWC, "coro_transform.py")
FUNNEL = "_forget_call"

# The families a surviving emission may cite — design 218 stages 1-3's measured
# deferrals, plus the spawn cell, which is not deferred at all: its slot lives in
# the group-owned cell, which is on the brief's TRUSTED list.
EXPECTED_FAMILIES = {
    "opt_closure",          # (a) a frame-resident closure is CALLED
    "address-taken",        # (b) `&x`, a nested call's receiver, a ref argument
    "void-payload",         # (c) `Slot<Void>` is not a type llvmlite will build
    "fixed-array",          # (d) `a[i] = v` writes through element storage
    "window-move",          # (e) DF-218h
    # (f) `rendering-operand` RETIRED Aug 22 with DF-218i — a rendering operand
    # is a borrow now, so a rendered frame local migrates to `Slot<T>`.
    # (g) `scrutinee-temp` RETIRED Aug 27 with design 247 — the `__hoistN` /
    # `__matchN` temps are take-read like every other hoist family now, and the
    # DF-210f forget that lived exactly there went with them. DF-215f (a double
    # release of any payload a driven arm moves out) is what the deferral cost.
    "spawn-cell",           # design 134's cell: TRUSTED, not deferred
}

# Files that may NAME `__saw_forget` without emitting one, and what they do with
# it. A consumer is the other half of the builtin: the transform is the only
# thing that writes the call, these are what happens to it afterwards.
CONSUMERS = {
    "sawc/typechecker/registration.py": "registers the builtin's name",
    "sawc/typechecker/expressions.py": "typechecks the call (arity + place)",
    "sawc/codegen/calls.py": "lowers it to the tag store",
}

# The ownership MARKS the transform stamps (218a section 6's M1 and M3). M2
# (`frame_move_read`) rides in M1's block and needs no pattern of its own.
MARK_ATTRS = ("frame_place_read", "frame_owning_read")

# The citation a stamp site carries, and how far above it the gate will look.
# A comment rather than an argument because a stamp is an attribute write, not a
# call — there is no parameter to put the family in without wrapping every one
# in a helper, which would hide the assignment the marks' own docs point at.
CITATION = "DEFERRED:"
CITATION_LOOKBACK = 16

# How a call site may spell its family argument. Anything else is an uncited
# emission — a literal string, a computed name, a default.
#   * a `FAM_*` constant     — the family named at the site
#   * `family`               — the funnel's own checked local (`_forget_stmt`)
#   * `<x>.result_defer_family` — the family `prepare` recorded for a `__result`
def _citation_ok(node):
    if isinstance(node, ast.Name):
        return node.id.startswith("FAM_") or node.id == "family"
    if isinstance(node, ast.Attribute):
        return node.attr == "result_defer_family"
    return False


def py_files(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if fn.endswith(".py"):
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def enclosing_functions(tree):
    """`lineno -> function name` for every line inside a function body, so a
    string literal can be attributed to the function that spells it."""
    owner = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                owner[line] = node.name
    return owner


def mark_stamps(tree):
    """Every `<expr>.frame_place_read = True` / `.frame_owning_read = True` in a
    module, as `(lineno, attribute)`. An augmented or annotated assignment is not
    how a mark is written, so plain `Assign` is the whole surface."""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Attribute) and target.attr in MARK_ATTRS:
                out.append((node.lineno, target.attr))
    return sorted(out)


def citation_above(lines, lineno):
    """The families cited for a stamp at `lineno`: the `DEFERRED:` comment on
    that line or in the CITATION_LOOKBACK lines above it, parsed into the family
    names it mentions. Returns `None` when there is no marker at all."""
    lo = max(0, lineno - 1 - CITATION_LOOKBACK)
    window = lines[lo:lineno]
    for text in reversed(window):
        if CITATION not in text:
            continue
        after = text.split(CITATION, 1)[1]
        return {f for f in EXPECTED_FAMILIES if f in after}
    return None


def main():
    failures = []

    # ---------------------------------------------------------------- rule 1
    for path in py_files(SAWC):
        rel = os.path.relpath(path, REPO)
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        if "__saw_forget" not in src:
            continue
        tree = ast.parse(src, filename=rel)
        owner = enclosing_functions(tree)
        spellings = [n for n in ast.walk(tree)
                     if isinstance(n, ast.Constant) and n.value == "__saw_forget"]
        if rel in CONSUMERS:
            continue
        if path != TRANSFORM:
            for n in spellings:
                failures.append(
                    (rel, n.lineno,
                     "spells `__saw_forget` outside the transform's funnel; a "
                     "consumer belongs in CONSUMERS, an emitter belongs in "
                     f"`{FUNNEL}`"))
            continue
        for n in spellings:
            if owner.get(n.lineno) != FUNNEL:
                failures.append(
                    (rel, n.lineno,
                     f"emits `__saw_forget` outside `{FUNNEL}` (in "
                     f"`{owner.get(n.lineno)}`) — route it through the funnel "
                     "so the emission cites its deferred family"))
        if len(spellings) != 1:
            failures.append(
                (rel, 0,
                 f"{len(spellings)} `__saw_forget` spellings; the funnel is the "
                 "one emission site and holds exactly one"))

    # ---------------------------------------------------------------- rule 2
    with open(TRANSFORM, encoding="utf-8") as fh:
        tsrc = fh.read()
    ttree = ast.parse(tsrc, filename="sawc/coro_transform.py")
    calls = 0
    for node in ast.walk(ttree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == FUNNEL):
            continue
        calls += 1
        if len(node.args) != 2 or node.keywords:
            failures.append(
                ("sawc/coro_transform.py", node.lineno,
                 f"`{FUNNEL}` takes (place, family) positionally; this call "
                 f"passes {len(node.args)} positional argument(s)"))
            continue
        if not _citation_ok(node.args[1]):
            failures.append(
                ("sawc/coro_transform.py", node.lineno,
                 f"uncited forget: family argument `{ast.unparse(node.args[1])}` "
                 "is not a FAM_* constant, a checked `family` local, or a "
                 "recorded `result_defer_family`"))
    if calls == 0:
        failures.append(
            ("sawc/coro_transform.py", 0,
             f"no `{FUNNEL}` call sites — if the last deferred family retired, "
             "delete the funnel and this gate together"))

    # ---------------------------------------------------------------- rule 3
    sys.path.insert(0, SAWC)
    import coro_transform  # noqa: E402
    declared = set(coro_transform.DEFERRED_FAMILIES)
    if declared != EXPECTED_FAMILIES:
        for extra in sorted(declared - EXPECTED_FAMILIES):
            failures.append(
                ("sawc/coro_transform.py", 0,
                 f"family `{extra}` is declared but not documented here — a new "
                 "deferral is a design decision and needs this file in the diff"))
        for gone in sorted(EXPECTED_FAMILIES - declared):
            failures.append(
                ("tools/test_forget_purge.py", 0,
                 f"family `{gone}` retired from the transform — drop it here in "
                 "the landing that migrated it"))

    # ------------------------------------------------------------- rules 4/5
    tlines = tsrc.splitlines()
    stamps = mark_stamps(ttree)
    for lineno, attr in stamps:
        cited = citation_above(tlines, lineno)
        if cited is None:
            failures.append(
                ("sawc/coro_transform.py", lineno,
                 f"uncited `{attr}` stamp: no `{CITATION}` comment within "
                 f"{CITATION_LOOKBACK} lines above it. Name the deferred family "
                 "that keeps this stamp alive — or, if the path it is on is "
                 "MIGRATED, delete the stamp: a `Slot` read is judged by the "
                 "ordinary rules and needs no assertion"))
        elif not cited:
            failures.append(
                ("sawc/coro_transform.py", lineno,
                 f"`{attr}` stamp cites no known family — a `{CITATION}` marker "
                 "must name at least one of DEFERRED_FAMILIES"))
    for path in py_files(SAWC):
        if path == TRANSFORM:
            continue
        rel = os.path.relpath(path, REPO)
        with open(path, encoding="utf-8") as fh:
            osrc = fh.read()
        if not any(a in osrc for a in MARK_ATTRS):
            continue
        for lineno, attr in mark_stamps(ast.parse(osrc, filename=rel)):
            failures.append(
                (rel, lineno,
                 f"stamps `{attr}` outside the transform. The marks are the "
                 "transform's own assertions about its output; a second "
                 "producer would have no deferred family to cite"))

    # The citation is CHECKED at emission, not merely spelled. Both refusals are
    # what makes rule 2 a property rather than a naming convention.
    from ast_nodes import Identifier  # noqa: E402
    for bogus in (None, "invented-family", ""):
        try:
            coro_transform._forget_call(Identifier(name="x"), bogus)
        except coro_transform.CoroTransformError:
            continue
        failures.append(
            ("sawc/coro_transform.py", 0,
             f"`{FUNNEL}` emitted with family {bogus!r}; it must refuse any "
             "family that is not one of DEFERRED_FAMILIES"))

    if failures:
        print("CITATION GATE FAILED — design 218 stage 4's exit criterion is "
              "broken.")
        print()
        print("Every `__saw_forget` the transform emits, and every M1/M3 mark it")
        print("stamps, must name the deferred census family that keeps it alive.")
        print("A MIGRATED path has neither: `Slot.take()` is the read and the")
        print("tag clear in one method body, and a slot read is judged by the")
        print("ordinary rules rather than asserted past them.")
        print()
        for rel, lineno, why in failures:
            where = f"  {rel}:{lineno}" if lineno else f"  {rel}"
            print(where)
            print(f"      {why}")
        print()
        print(f"{len(failures)} finding(s).")
        return 1

    print(f"citation gate: 1 forget emission site (`{FUNNEL}`) with {calls} cited "
          f"call site(s), {len(stamps)} cited M1/M3 stamp(s), "
          f"{len(declared)} deferred famil(ies); zero uncited sites.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""THE WINDOW SEAM GATE (design 275 U3's reuse obligation).

The user's ruling of Sep 20 was to build the STATEMENT-SCOPED WINDOW with `for`
as its first client — "not a for-loop feature" — so that the generic
scoped-borrow statement a follow-up specifies adds its syntax, its typechecking
client and its acquisition/result binding, and NO second implementation of root
accounting, pinning, suspension persistence or exit cleanup (codex c44).

That is a claim about where knowledge LIVES, and the lead's validation of U3 was
a grep: `ForLoop` in the window chokepoint and in the transform's window
handling must find only the ADAPTER. A grep a human runs once is a claim that
rots the next time somebody reaches for `stmt.variable` inside the common layer,
which is exactly how a "generic" mechanism becomes its first client's. So it is
a lane.

WHAT IT CHECKS, and why each one is the thing that would go wrong:

  1. `sawc/windows.py` — the record and the chokepoint — names no AST class and
     no iteration vocabulary in its CODE. Prose may discuss `ForLoop`; the
     module must not import or touch one. The failure this catches is the
     obvious one: a convenience that reads the loop variable off the extent.

  2. The record's resource slot is GENERIC (B1). `windows.py` declares
     `resource_name` / `resource_type` and nothing called `iterator`, `iter`,
     `next` or `element`. A record that names an iterator is a record the
     accessor client cannot use.

  3. The chokepoint's docstring NAMES ITS CLIENTS (obligation 1's funnel rule),
     and every client name it lists resolves to a routine that exists.

  4. `codegen/loops.py`'s window routines take the LOOP NODE and the resource
     slot and read neither `variable` nor `element_type` off it — the sync
     lowering of a window is one routine for any client (the reuse
     obligation's point 3).

  5. The `for` ADAPTER is the only thing in `typechecker/borrowing.py` that
     names `ForLoop`-shaped state. Its two entry points exist and the
     conflict/fence machinery beside them does not mention loops.

  6. The transform's window handling reaches the record through the STATEMENT's
     `window` field rather than re-deriving it, and its one `ForLoop`-shaped
     routine is the normalization adapter.

Every check reads SOURCE. That is deliberate and is the same choice
`tools/test_coro_discovery.py` made: the property is structural, and a
behavioural test would pass just as happily on a mechanism that had quietly
grown a second copy.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SAWC = os.path.join(REPO, "sawc")

WINDOWS = os.path.join(SAWC, "windows.py")
BORROWING = os.path.join(SAWC, "typechecker", "borrowing.py")
LOOPS = os.path.join(SAWC, "codegen", "loops.py")
TRANSFORM = os.path.join(SAWC, "coro_transform.py")


def _read(path):
    with open(path) as fh:
        return fh.read()


def _code_lines(src):
    """Every line of `src` that is not inside a docstring and is not a comment.

    Crude on purpose — a module-level triple-quoted string and a `#` comment are
    the two places the seam's own PROSE lives, and prose is allowed to name
    `ForLoop` (it has to: the docstrings are where the rule is written down).
    What must stay clean is the code.
    """
    out = []
    in_doc = False
    quote = None
    for line in src.splitlines():
        stripped = line.strip()
        if in_doc:
            if quote in line:
                in_doc = False
            continue
        if stripped.startswith(('"""', "'''")):
            quote = stripped[:3]
            rest = stripped[3:]
            if quote not in rest:
                in_doc = True
            continue
        if '"""' in line or "'''" in line:
            # A docstring opened mid-line (a def's, say). Take the prefix.
            idx = min(i for i in (line.find('"""'), line.find("'''")) if i >= 0)
            head = line[:idx]
            quote = line[idx:idx + 3]
            if line.count(quote) < 2:
                in_doc = True
            out.append(head)
            continue
        if stripped.startswith("#"):
            continue
        out.append(line.split("#", 1)[0] if "#" in line else line)
    return out


# --------------------------------------------------------------------------- #
# 1 + 2: the record and the chokepoint know nothing about loops
# --------------------------------------------------------------------------- #

#: Vocabulary that would mean the common layer had learned its first client's
#: shape. `resource` is what B1 calls the slot, and is the point.
_CLIENT_WORDS = ("ForLoop", "iterable", "element_type", "Iterator",
                 "iterator", "__iter", "next(")


def check_chokepoint_is_client_free():
    problems = []
    for line_no, line in enumerate(_code_lines(_read(WINDOWS)), 1):
        for word in _CLIENT_WORDS:
            if word in line:
                problems.append(
                    f"sawc/windows.py:{line_no}: the window chokepoint's CODE "
                    f"names `{word}`. The record and the table are the common "
                    f"layer — root charge, persistent referent slot, "
                    f"suspension state, ordered cleanup — and a client's "
                    f"vocabulary in it is the first step of the mechanism "
                    f"becoming its first client's (design 275 U3, codex c44). "
                    f"Prose may name it; code may not.")
    src = _read(WINDOWS)
    for slot in ("resource_name", "resource_type"):
        if slot not in src:
            problems.append(
                f"sawc/windows.py: the record no longer declares `{slot}`. B1 "
                f"says the record holds a GENERIC resource slot, not a field "
                f"named `__iter` and not an `Iterator`-shaped payload — the "
                f"`for` client puts an iterator in it and a future accessor "
                f"client would put a lend result.")
    return problems


# --------------------------------------------------------------------------- #
# 3: the chokepoint names its clients, and they exist
# --------------------------------------------------------------------------- #

def check_chokepoint_names_its_clients():
    src = _read(WINDOWS)
    problems = []
    if "CLIENTS" not in src:
        problems.append(
            "sawc/windows.py: `WindowTable`'s docstring no longer names its "
            "CLIENTS. Obligation 1: a funnel names its entry points, and this "
            "one's whole purpose is that a second client is a call rather than "
            "a second implementation.")
        return problems
    borrowing = _read(BORROWING)
    for entry in ("open_for_window", "close_for_window"):
        if f"`{entry}`" not in src and entry not in src:
            problems.append(
                f"sawc/windows.py: the client list does not name `{entry}`.")
        if f"def {entry}(" not in borrowing:
            problems.append(
                f"the client list names `{entry}`, which "
                f"`typechecker/borrowing.py` does not define.")
    return problems


# --------------------------------------------------------------------------- #
# 4: codegen's window routines are one routine for any client
# --------------------------------------------------------------------------- #

def check_codegen_lowering_is_generic():
    src = _read(LOOPS)
    problems = []
    for name in ("_open_window_resource", "_close_window_resource"):
        if f"def {name}(" not in src:
            problems.append(
                f"sawc/codegen/loops.py: `{name}` is gone. The sync lowering "
                f"of a window — the resource's slot and the "
                f"drop-before-charge-end order — is ONE routine for any "
                f"client (design 275 U3's reuse obligation, point 3).")
            continue
        body = _routine_body(src, name)
        # Word-bounded: `self.variables` is codegen's own symbol table and is
        # not the loop's `stmt.variable`.
        for word in (r"ForLoop", r"\.variable\b", r"\.element_type\b",
                     r"\.iterable\b", r"loop_stack", r"RangeExpr"):
            if re.search(word, body):
                problems.append(
                    f"sawc/codegen/loops.py: `{name}` names `{word}`. It is "
                    f"handed the resource's TYPE and its slot and nothing "
                    f"else; reading a client's own shape out of a node is the "
                    f"duplication the reuse obligation forbids.")
    return problems


def _routine_body(src, name):
    """The CODE of one `def name(...)`, by indentation, docstring stripped.

    The docstring is where the routine explains what it is NOT allowed to
    know, so leaving it in would make every such explanation a failure.
    """
    lines = src.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(f"def {name}("):
            indent = len(line) - len(line.lstrip())
            body = []
            for nxt in lines[i + 1:]:
                if nxt.strip() and (len(nxt) - len(nxt.lstrip())) <= indent:
                    break
                body.append(nxt)
            return "\n".join(_code_lines("\n".join(body)))
    return ""


# --------------------------------------------------------------------------- #
# 5: the `for` adapter is the only loop-shaped thing in the typechecker half
# --------------------------------------------------------------------------- #

#: The routines that ARE the adapter, and may therefore speak of loops.
_ADAPTER = ("open_for_window", "close_for_window", "borrowing_head_receiver",
            "borrowing_head_root")


def check_adapter_is_the_only_loop_shape():
    src = _read(BORROWING)
    problems = []
    for entry in ("open_for_window", "close_for_window"):
        if f"def {entry}(" not in src:
            problems.append(
                f"typechecker/borrowing.py: the `for` adapter's `{entry}` is "
                f"gone.")
    # The conflict machinery and the fence are the COMMON half of this module
    # and must not name the client either.
    for name in ("window_conflict", "report_window_conflict",
                 "check_window_access", "reject_borrowing_value",
                 "check_borrowing_fence"):
        body = _routine_body(src, name)
        if not body:
            problems.append(
                f"typechecker/borrowing.py: `{name}` is gone; it is one of the "
                f"named readers of the window charge and of the fence.")
            continue
        for word in ("ForLoop", "iterable", "element_type"):
            if word in body:
                problems.append(
                    f"typechecker/borrowing.py: `{name}` names `{word}`. The "
                    f"conflict question and the fence are asked of a ROOT and "
                    f"of a TYPE; the loop belongs to the adapter.")
    return problems


# --------------------------------------------------------------------------- #
# 6: the transform reads the RECORD, and its loop shape is the normalization
# --------------------------------------------------------------------------- #

def check_transform_reads_the_record():
    src = _read(TRANSFORM)
    problems = []
    if "_normalize_collection_for" not in src:
        problems.append(
            "coro_transform.py: `_normalize_collection_for` is gone. SL-317's "
            "split IS that rewrite — a spanning collection `for` becomes the "
            "`while let` it denotes, so `_split_while` and `_split_if_let` do "
            "the work and there is no third split routine.")
    # The retired refusal must not come back: a collection `for` reaching
    # `_split_for` is an INVARIANT failure now, not a clean rejection.
    split_for = _routine_body(src, "_split_for")
    if split_for and "LedgerMiss" not in split_for:
        problems.append(
            "coro_transform.py: `_split_for`'s non-range arm no longer raises "
            "an invariant failure. A spanning collection `for` is rewritten "
            "before the split walk, so one reaching here means the "
            "normalization missed a statement — which is a compiler bug and "
            "not a program the author can fix.")
    return problems


CHECKS = (
    ("the chokepoint's code knows nothing about its client",
     check_chokepoint_is_client_free),
    ("the chokepoint names its clients and they exist",
     check_chokepoint_names_its_clients),
    ("codegen's window lowering is one routine for any client",
     check_codegen_lowering_is_generic),
    ("the `for` adapter is the only loop-shaped thing in the typechecker half",
     check_adapter_is_the_only_loop_shape),
    ("the transform reads the record, and its loop shape is the normalization",
     check_transform_reads_the_record),
)


def main():
    failures = []
    for label, check in CHECKS:
        problems = check()
        if problems:
            failures.append((label, problems))
    if failures:
        print("WINDOW SEAM GATE FAILED — design 275 U3's reuse obligation.\n")
        for label, problems in failures:
            print(f"  {label}:")
            for problem in problems:
                print(f"    - {problem}")
            print()
        print("The window is a STRUCTURE with `for` as its first client. A")
        print("second client should be an `open_window` call and an adapter,")
        print("never a second implementation of root accounting, pinning,")
        print("suspension persistence or exit cleanup (codex c44).")
        return 1
    print(f"window seam gate: {len(CHECKS)} checks — the chokepoint names no "
          f"client vocabulary, its client list resolves, the sync lowering is "
          f"one routine, the conflict/fence half names no loop, and the "
          f"transform's loop shape is the normalization.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

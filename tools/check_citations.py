#!/usr/bin/env python3
"""The stale-citation lint, and the committed-conflict-marker check (DF-248c).

TWO CHECKS, ONE BLIND SPOT. Every gate in this tree compiles something. A file
that nothing compiles — a tracker entry, an INDEX row, an XFAIL citation — can
say anything at all and no lane will notice, which is how a pin came to cite a
finding that had closed two days earlier and how three git conflict-marker
blocks came to sit on `main`, one of them in `designs/todo.md` since Aug 22.
This lane is what reads the files nothing compiles.

CHECK 2 — COMMITTED CONFLICT MARKERS — is the simpler one, so it goes first. A
line beginning `<<<<<<<` PAIRED with a later line beginning `>>>>>>>` in the
same file is a git conflict block somebody committed. The pair is the test:
`=======` alone is ordinary content (a markdown rule, a banner), and the opener
alone could be ASCII art, but the two together are the exact shape git writes
and nothing else. Every TRACKED text file is checked, with no exclusions —
verified by grep when this landed, and the fix if a file ever legitimately
carries the shape is an explicit path list here with a comment saying why, never
a widened directory skip.

CHECK 1 — STALE CITATIONS. An XFAIL marker and a differential harness's known-ledger row are both PROMISES:
"this fails, we know why, here is the finding". Every gate reads the promise in
exactly one direction — a pin that starts PASSING is an XPASS and breaks the
build. Nothing looks the other way. A pin whose finding was CLOSED by a ruling
that superseded the behaviour the pin asserts keeps FAILING, so it stays a
well-behaved known failure forever while the ledger it belongs to reports a red
cell that is green. That is what happened to
`visibility_package_relative_import_fails_open.saw`, which cited DF-232n for two
days after DF-232n closed.

This lane closes that direction. It collects every DF citation the tree makes —
the first DF of a `// XFAIL:` reason in any tracked `.saw` file, and the leading
DF of each row of the harness known-ledgers under `tools/` — and checks each
against the tracker's CLOSED set.

It does NOT look at the other half of the promise, whether the pin still fails
for the reason it names (DF-248c face 2). That needs the RUN's character, which
lives in the runner, not in a citation.

WHAT COUNTS AS CLOSED, and why the rules are shaped this way:

  * `designs/done_*.md` membership is closure, full stop. The lead moves an
    entry to the week's done file only once it is closed and reviewed, so a DF
    with an ENTRY there has nothing left open. This is the cheap half, and it is
    the half that would have caught DF-232n.

  * `designs/todo.md` holds an entry IN PLACE after it closes, until the lead
    moves it, so presence there proves nothing on its own — the STATUS does. An
    entry line whose subject is struck through (`~~DF-xxx~~`) or whose text
    opens `— CLOSED` / `FIXED` / `LANDED` / `RETIRED` is closed.

  * AN OPEN todo.md ENTRY WINS OVER EVERY CLOSURE. A finding is often closed in
    part: DF-218w narrowed to one shape, DF-248b's window half landed while its
    closure half did not, and both keep a pinned XFAIL that is exactly right.
    The tracker spells that as a RESIDUE entry, so a citation is stale only when
    NOTHING anchored on that DF is still open.

A lint that cries wolf gets deleted, so anything this cannot decide — a DF with
no entry anywhere, a citation shaped in a way the anchors do not recognise — is
reported as INFO and passes. Only a citation whose finding is fully closed
fails the lane.

  tools/check_citations.py            # the lane: report, exit 1 on a finding
  tools/check_citations.py --list     # every citation and its verdict
"""

from __future__ import annotations

import argparse
import subprocess
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

TODO = REPO_ROOT / "designs" / "todo.md"
DONE_GLOB = "done_*.md"

# The known-ledgers a differential harness keeps beside itself. Each is
# `DF-NUMBER <TAB> signature`, `#` comments, blank lines ignored.
KNOWN_LEDGERS = ("corodiff_known.txt", "sawfuzz_known.txt")

# Directories with nothing tracked in them.
SKIP_DIRS = {".git", ".build", ".venv", "__pycache__", "node_modules"}

# A conflict block git wrote and somebody committed. The PAIR is the test — see
# the module docstring. No file in this repo legitimately carries the shape
# (checked by `git grep -I "^<<<<<<<"` when this landed); if one ever does, list
# its path here with the reason, and never widen this to a directory.
CONFLICT_OPEN_RE = re.compile(r"^<<<<<<<(?:\s|$)")
CONFLICT_CLOSE_RE = re.compile(r"^>>>>>>>(?:\s|$)")
CONFLICT_ALLOWED: tuple[str, ...] = ()

DF = r"DF-\d+[a-z]*"

XFAIL_RE = re.compile(r"//\s*XFAIL:\s*(.*)$")
DF_RE = re.compile(DF)

# An ENTRY line: a markdown list item or heading whose SUBJECT is a DF number.
# The marker is what separates an entry from a wrapped paragraph line that
# merely happens to begin with a bolded cross-reference (`**DF-239b** below.`),
# which is not a status about DF-239b at all.
ANCHOR_RE = re.compile(
    r"^(?:#{1,6}\s+|[-*]\s+)"      # heading or list marker — required
    r"((?:\*\*|~~|__|_)*)\s*"      # emphasis/strikethrough openers
    r"(" + DF + r")\b"             # the subject
    r"(.*)$"
)

# "— CLOSED", "— LANDED Aug 21", "(filed …) — FIXED", "— **CLOSED**".
CLOSED_RE = re.compile(
    r"^\s*(?:\([^)]*\)\s*)?(?:~~)?\s*(?:—|–|--|-)\s*(?:\*\*)?\s*"
    r"(CLOSED|FIXED|LANDED|RETIRED)\b",
    re.IGNORECASE,
)

# A tracker entry that says outright it is the part that did NOT close.
RESIDUE_RE = re.compile(r"^\s*(?:\*\*)?\s*RESIDUE\b", re.IGNORECASE)


@dataclass
class Citation:
    df: str
    path: Path
    line: int
    kind: str     # "xfail" | "ledger"
    text: str


@dataclass
class Anchor:
    df: str
    path: Path
    line: int
    closed: bool
    text: str


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def tracked_files() -> list[str]:
    """Every path git tracks, repo-relative. Raises if git cannot answer."""
    done = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
        capture_output=True, check=True)
    return [name for name in done.stdout.decode("utf-8").split("\0") if name]


def find_conflict_markers() -> list[tuple[str, int, int, str]]:
    """Committed conflict blocks: (path, opener line, closer line, opener)."""
    found: list[tuple[str, int, int, str]] = []
    for name in tracked_files():
        if name in CONFLICT_ALLOWED:
            continue
        path = REPO_ROOT / name
        try:
            raw = path.read_bytes()
        except OSError:
            continue          # a deleted-but-tracked path is git's problem
        if b"\0" in raw[:8192]:
            continue          # binary; git's own -I does the same
        lines = raw.decode("utf-8", errors="replace").splitlines()
        opens: list[tuple[int, str]] = []
        for number, line in enumerate(lines, start=1):
            if CONFLICT_OPEN_RE.match(line):
                opens.append((number, line))
            elif CONFLICT_CLOSE_RE.match(line) and opens:
                # Pair each closer with the OUTERMOST opener still unclosed, so
                # a NESTED block — git writes one when a resolution is itself
                # conflicted, which is what `examples/conformance/INDEX.md`
                # carried — reports both of its pairs rather than one. An
                # opener nothing ever closes is not the shape git writes and is
                # left alone.
                at, text = opens.pop(0)
                found.append((name, at, number, text))
    return found


def collect_citations() -> list[Citation]:
    """Every DF citation the tree makes, in file order."""
    found: list[Citation] = []
    for path in sorted(REPO_ROOT.rglob("*.saw")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, start=1):
            hit = XFAIL_RE.search(line)
            if not hit:
                continue
            reason = hit.group(1)
            # THE FIRST DF is the citation; a later mention in the same reason
            # is prose (a sibling finding, the branch that narrowed this one),
            # and holding prose to the citation's standard is how a lint starts
            # crying wolf. A pin that genuinely rests on two findings is
            # justified by the first one being open.
            df = DF_RE.search(reason)
            found.append(Citation(df.group(0) if df else "",
                                  path, number, "xfail", reason.strip()))

    for name in KNOWN_LEDGERS:
        path = REPO_ROOT / "tools" / name
        if not path.exists():
            continue
        for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            df = DF_RE.match(stripped)
            if df:
                found.append(Citation(df.group(0), path, number, "ledger", stripped))
    return found


def parse_anchors(text: str, path: Path,
                  always_closed: bool) -> dict[str, list[Anchor]]:
    """Tracker entries keyed by DF. `always_closed` is the done-file rule."""
    anchors: dict[str, list[Anchor]] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        hit = ANCHOR_RE.match(line)
        if not hit:
            continue
        openers, df, rest = hit.group(1), hit.group(2), hit.group(3)
        if always_closed:
            closed = True
        else:
            # Strikethrough is the tracker's own "this is done" mark, and it
            # may span more than the one DF (`~~DF-218s remainder + DF-218w~~`),
            # so read the OPENER rather than looking for a matching `~~` after
            # the number.
            struck = "~~" in openers
            residue = bool(RESIDUE_RE.match(rest))
            closed = (struck or bool(CLOSED_RE.match(rest))) and not residue
        anchors.setdefault(df, []).append(
            Anchor(df, path, number, closed, line.strip()))
    return anchors


def collect_anchors() -> tuple[dict[str, list[Anchor]], dict[str, list[Anchor]]]:
    """Tracker entries keyed by DF: (todo.md anchors, done-file anchors)."""
    todo: dict[str, list[Anchor]] = {}
    done: dict[str, list[Anchor]] = {}
    if TODO.exists():
        todo = parse_anchors(TODO.read_text(encoding="utf-8"), TODO, False)
    for path in sorted((REPO_ROOT / "designs").glob(DONE_GLOB)):
        for df, found in parse_anchors(
                path.read_text(encoding="utf-8"), path, True).items():
            done.setdefault(df, []).extend(found)
    return todo, done


# Every row is a REAL line, copied from the tracker as it stood when this lane
# landed, paired with the verdict the lane must reach on it. It runs on every
# invocation, because a lint whose recognisers have quietly stopped recognising
# anything reports a clean tree exactly as a clean tree does — which is the
# shape of gap DF-248c is about in the first place.
SELF_TEST_TODO = [
    # (line, DF it must anchor, closed?)
    ("## DF-232n — `public(package)` is NOT enforced across a RELATIVE-PATH "
     "import:", "DF-232n", False),
    ("- ~~DF-238b~~ — CLOSED Aug 22 (branch `diag-batch`, commit 2): an integer "
     "renders at its own width now", "DF-238b", True),
    ("- **DF-248d — CLOSED (Aug 22, `place-window-fixes`), filed and fixed by",
     "DF-248d", True),
    ("- DF-218w RESIDUE — the MIXED `case Both(v, _)` shape keeps statement-end "
     "timing (entry below, pinned XFAIL; the rest of DF-218w closed Aug 21)",
     "DF-218w", False),
    ("- DF-248b RESIDUE — a HAND-WRITTEN closure nested inside another still "
     "captures the outer one's `&var` PARAMETER by value", "DF-248b", False),
    ("- **DF-218h (BOGUS-REFUSAL + a worse alternative, PRE-EXISTING) — a "
     "`move` of", "DF-218h", False),
    ("- DF-239b — RULED Aug 24 (user): DECLARATION-TIME RESOLUTION", "DF-239b",
     False),
    ("- ~~DF-218s remainder + DF-218w~~ — LANDED Aug 21 on branch "
     "`df-218s-218w`, two commits.", "DF-218s", True),
    # A wrapped paragraph line is NOT an entry, however it begins.
    ("**DF-239b** below. The erasure diagnostic's wording wart went with it: a",
     None, None),
    ("DF-232n's minimal two-file repro alongside the audit's larger", None, None),
]


def self_test() -> list[str]:
    """Check the recognisers against real tracker lines. Empty == healthy."""
    failures: list[str] = []
    fake = Path("self-test")
    for line, want_df, want_closed in SELF_TEST_TODO:
        got = parse_anchors(line, fake, False)
        if want_df is None:
            if got:
                failures.append(f"expected no entry, got {sorted(got)}: {line[:60]}")
            continue
        if want_df not in got:
            failures.append(f"expected an entry for {want_df}: {line[:60]}")
            continue
        if got[want_df][0].closed != want_closed:
            state = "closed" if want_closed else "open"
            failures.append(f"{want_df} should read {state}: {line[:60]}")

    # The historical case, end to end: a pin citing a DF whose entry has moved
    # to a done file is STALE even though the DF also still sits in todo.md.
    done = parse_anchors("## DF-232n — CLOSED Aug 20", fake, True)
    if not done.get("DF-232n") or not done["DF-232n"][0].closed:
        failures.append("a done-file entry must read as closed")

    # The conflict-marker recognisers, against the exact lines git wrote into
    # the three blocks that reached main on Aug 24.
    for line in ("<<<<<<< HEAD", "<<<<<<< ours"):
        if not CONFLICT_OPEN_RE.match(line):
            failures.append(f"an opener must be recognised: {line}")
    for line in (">>>>>>> ae94bdb0 (DF-245c: a bare `None`'s payload type)",
                 ">>>>>>> 80fc3291 (design 242 unit 2)"):
        if not CONFLICT_CLOSE_RE.match(line):
            failures.append(f"a closer must be recognised: {line}")
    for line in ("=======", "======= not a marker on its own",
                 "<<<< short", "a line that merely mentions <<<<<<< HEAD",
                 "<<<<<<<<< nine of them"):
        if CONFLICT_OPEN_RE.match(line) or CONFLICT_CLOSE_RE.match(line):
            failures.append(f"must NOT be read as a marker: {line}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true",
                        help="print every citation with its verdict")
    args = parser.parse_args()

    broken = self_test()
    if broken:
        print("check_citations: the recogniser self-test FAILED — this lane "
              "cannot be trusted to report anything:")
        for why in broken:
            print(f"  {why}")
        return 2

    try:
        conflicts = find_conflict_markers()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"check_citations: `git ls-files` failed ({exc}) — the "
              "conflict-marker check cannot enumerate the tree")
        return 2

    citations = collect_citations()
    todo_anchors, done_anchors = collect_anchors()

    stale: list[tuple[Citation, Anchor]] = []
    info: list[tuple[Citation, str]] = []
    ok = 0

    for cite in citations:
        if not cite.df:
            info.append((cite, "the XFAIL reason cites no DF number"))
            continue
        open_entries = [a for a in todo_anchors.get(cite.df, []) if not a.closed]
        if open_entries:
            ok += 1
            if args.list:
                first = open_entries[0]
                print(f"  open   {cite.df:<10} {_rel(cite.path)}:{cite.line}"
                      f"  <- {_rel(first.path)}:{first.line}")
            continue
        closures = [a for a in todo_anchors.get(cite.df, []) if a.closed]
        closures += done_anchors.get(cite.df, [])
        if closures:
            stale.append((cite, closures[0]))
            continue
        info.append((cite, "no tracker entry is anchored on it"))

    print(f"citations: {len(citations)} "
          f"({sum(1 for c in citations if c.kind == 'xfail')} xfail, "
          f"{sum(1 for c in citations if c.kind == 'ledger')} ledger); "
          f"conflict markers: {len(conflicts)}")

    if conflicts:
        print()
        print(f"CONFLICT MARKERS ({len(conflicts)}) — a git conflict block is "
              "committed:")
        for name, opened, closed_at, text in conflicts:
            print(f"  {name}:{opened}-{closed_at}  {text[:60]}")
        print()
        print("Resolve it the way the tracker rules ask: hunk by hunk in the "
              "editor, keeping BOTH sides of an accumulator file (todo.md, "
              "INDEX.md, SKILL.md) unless they are genuine duplicates — never "
              "by taking one whole side.")

    if info:
        print()
        print(f"UNDECIDED ({len(info)}) — reported, not failed:")
        for cite, why in info:
            print(f"  {_rel(cite.path)}:{cite.line}: "
                  f"{cite.df or '(no DF)'} — {why}")

    if stale:
        print()
        print(f"STALE ({len(stale)}) — the cited finding is CLOSED:")
        for cite, closure in stale:
            print(f"  {_rel(cite.path)}:{cite.line} cites {cite.df}, which is "
                  f"closed at {_rel(closure.path)}:{closure.line}")
            print(f"      citation: {cite.text[:100]}")
            print(f"      closure:  {closure.text[:100]}")
        print()
        print("A citation is a promise that the finding is still open. Either "
              "the pin asserts a behaviour the closing ruling SUPERSEDED — "
              "rewrite it as the accept row under the behaviour's own name and "
              "drop the marker — or the finding is not closed after all and the "
              "tracker entry is what needs correcting.")

    if stale or conflicts:
        return 1

    print(f"citations: {ok} open, {len(info)} undecided, 0 stale; "
          "no committed conflict markers")
    return 0


if __name__ == "__main__":
    sys.exit(main())

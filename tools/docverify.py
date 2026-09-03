#!/usr/bin/env python3
"""docverify — compile every Saw example the documentation shows (design 262).

No gate had ever compiled a documentation example before this lane existed, so
every doc example was as correct as the last person to read it. This one
extracts each fenced block from the sources below and holds it to what its
fence info string CLAIMS.

ENTRY POINTS (brief obligation 1 — this list IS the funnel; adding a fifth
source is editing `SOURCES` and nothing else):

    README.md
    CLAUDE.md
    LANGUAGE_SPEC.md
    .claude/skills/saw-lang/SKILL.md

THE FOUR MARKERS (design 262 §1, as corrected by Amendment A):

    ```saw            a complete compilation unit. Compiled with `-c` AS
                      WRITTEN — object only, no `main` required, no link — so
                      a declaration set and an example naming an undefined
                      `extern` both count. Must SUCCEED.

    ```saw-body       a statement sequence. The HARNESS hoists the block's
                      top-level declarations — imports, and any struct / enum
                      / trait / extension / type / func / static / extern the
                      example declares beside its statements — and wraps what
                      is left in a synthesized `func main() { }`. The scaffold
                      lives here, never in the doc text, which is what keeps
                      §1's no-hidden-lines rule intact. Must SUCCEED.

    ```saw-error      a program the compiler must REFUSE. A first-line
                      `// error-contains: <substring>` pin is MANDATORY and
                      the emitted diagnostics must contain it. Without the pin
                      the marker tests nothing: `sawc` says ``no `main`
                      function found`` for any main-less input before it
                      reaches most claimed checks, which passed ~300 of the
                      440 census blocks on the exit code alone. A traceback or
                      an `internal compiler error` is always a failure, pin or
                      no pin.

    ```saw-fragment   deliberately incomplete — an elision, a signature
                      sketch, one half of a multi-file example. EXEMPT from
                      compilation but COUNTED: the per-source exempt fraction
                      is printed on every run, so erosion toward "everything
                      is a fragment" is loud.

An untagged fence holding Saw code is a LANE ERROR — classification is not
optional, and a block nobody classified is a block nobody checked. Untagged
fences that hold shell transcripts, output or grammar sketches are ignored;
tag one `text` if the Saw heuristic below trips on it.

SHAPING, and the one thing it does that the marker does not say. `saw` and
`saw-body` each have exactly one shape. `saw-error` tries the AS-IS shape
first and, only when that shape's diagnostics are VACUOUS — nothing but
``no `main` function found`` and/or a parse/lex error on line 1-2, which is
what a bare statement sequence produces before any semantic check runs — tries
the `saw-body` wrap and judges the pin against that. The pin still has to
match a real diagnostic either way, so this widens what the lane can verify
without weakening what a pass means: an error demo written as a statement
sequence gets checked against its claimed error instead of being demoted to a
fragment. Amendment A's rejection rule is what remains: a block whose only
diagnostics are vacuous in BOTH shapes fails unless its pin names exactly
that.

This lane does NOT re-check the spec's std module table — `preludegate`
(tools/test_prelude_gate_doc.py) owns that and has since design 194.

    tools/docverify.py                 # every source
    tools/docverify.py --source README.md
    tools/docverify.py --jobs 4 -v
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# The funnel's entry points. Everything else in this file is generic over them.
SOURCES = [
    "README.md",
    "CLAUDE.md",
    "LANGUAGE_SPEC.md",
    ".claude/skills/saw-lang/SKILL.md",
]

MARKERS = ("saw", "saw-body", "saw-error", "saw-fragment")

SCRATCH = REPO / ".build" / "docverify"

PIN_RE = re.compile(r"^\s*//\s*error-contains:\s*(?P<pin>.+?)\s*$")

# A bare fence holding any of these reads as Saw and must be classified.
SAW_HINT_RE = re.compile(
    r"^\s*(func\s+\w|let\s+\w|var\s+\w|struct\s+\w|enum\s+\w|trait\s+\w"
    r"|extension\s+\w|import\s+\w|public\s+|static\s+\w+\s*:"
    r"|match\s+\w|guard\s+let\s|if\s+let\s|print\()",
    re.M,
)

# The two diagnostics that say "this block is not a top-level compilation
# unit" and NOTHING about what the code means. Amendment A names them by
# position (``no main`` / a line-1 parse error); keying on the MESSAGE is the
# same rule stated exactly — a block that opens with declarations and ends
# with statements earns the second one well past line 1.
NO_MAIN_RE = re.compile(r"no `?main`? function found")
TOPLEVEL_RE = re.compile(
    r"Expected import, export, module, struct, enum, trait, extension, type, "
    r"extern, or function declaration")
ICE_RE = re.compile(r"internal compiler error|Traceback \(most recent call last\)")

# sawc colours its diagnostics; the pin is matched against the plain text.
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# What opens a top-level declaration, for the `saw-body` hoist.
DECL_RE = re.compile(
    r"^(import|struct|enum|trait|extension|type|func|static|extern|public|unsafe|@)\b")


@dataclass
class Block:
    source: str
    line: int  # 1-based line of the opening fence
    info: str  # the fence info string, "" when bare
    body: str

    @property
    def where(self) -> str:
        return f"{self.source}:{self.line}"


@dataclass
class Result:
    block: Block
    marker: str
    ok: bool
    detail: str = ""
    shape: str = "as-is"


@dataclass
class SourceCounts:
    compiled: int = 0
    refused: int = 0
    exempt: int = 0
    failures: list[Result] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.compiled + self.refused + self.exempt


def extract(source: str) -> list[Block]:
    """Every fenced block of one source, in document order.

    Fences may be indented; the opening indent is stripped from the body so a
    block nested in a list item compiles as written.
    """
    text = (REPO / source).read_text(encoding="utf-8")
    blocks: list[Block] = []
    fence: re.Match[str] | None = None
    open_line = 0
    indent = ""
    info = ""
    body: list[str] = []
    for n, line in enumerate(text.splitlines(), start=1):
        m = re.match(r"^(?P<indent>\s*)```(?P<info>.*)$", line)
        if fence is None:
            if m:
                fence = m
                open_line = n
                indent = m.group("indent")
                info = m.group("info").strip()
                body = []
            continue
        if m and not m.group("info").strip():
            blocks.append(Block(source, open_line, info, "\n".join(body)))
            fence = None
            continue
        body.append(line[len(indent):] if line.startswith(indent) else line)
    return blocks


def classify(block: Block) -> str | None:
    """The marker this block is held to, or None when it is not Saw at all."""
    if block.info in MARKERS:
        return block.info
    if block.info:
        return None  # bash, toml, text — an explicit non-Saw tag
    if SAW_HINT_RE.search(block.body):
        return "UNTAGGED"
    return None


def split_declarations(body: str) -> tuple[list[str], list[str]]:
    """Split a block into its top-level declarations and its statements.

    A declaration begins at brace depth zero on a line opening with one of the
    declaration keywords and runs until its braces close. Everything else at
    depth zero is a statement. Declaration bodies are never inspected, so a
    `func` holding statements stays whole.
    """
    decls: list[str] = []
    stmts: list[str] = []
    pending: list[str] | None = None
    depth = 0
    for line in body.splitlines():
        if pending is None:
            if depth == 0 and DECL_RE.match(line):
                pending = [line]
                depth = line.count("{") - line.count("}")
                if depth <= 0:
                    decls.extend(pending)
                    pending, depth = None, 0
            else:
                stmts.append(line)
            continue
        pending.append(line)
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            decls.extend(pending)
            pending, depth = None, 0
    if pending is not None:
        decls.extend(pending)
    return decls, stmts


def wrap_body(body: str) -> str:
    """The `saw-body` shape: declarations hoisted, statements inside a `main`."""
    decls, stmts = split_declarations(body)
    return "\n".join(decls + ["func main() {"] + stmts + ["}"]) + "\n"


def compile_source(text: str, stem: str, python: str) -> tuple[bool, str]:
    """One `sawc -c` over `text`. Returns (succeeded, combined output)."""
    SCRATCH.mkdir(parents=True, exist_ok=True)
    src = SCRATCH / f"{stem}.saw"
    src.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    obj = SCRATCH / f"{stem}.o"
    try:
        proc = subprocess.run(
            [python, str(REPO / "sawc" / "sawc.py"), str(src), "-c", "-o", str(obj)],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        return False, "docverify: sawc timed out after 180s"
    return proc.returncode == 0, ANSI_RE.sub("", (proc.stdout or "") + (proc.stderr or ""))


def vacuous(output: str) -> bool:
    """True when nothing but scaffolding noise came back.

    ``no `main` function found`` and the top-level-declaration parse error are
    what a main-less file and a statement sequence produce before any check a
    doc could be demonstrating has run.
    """
    lines = [ln.strip() for ln in output.splitlines() if ln.strip().startswith("error:")
             or ln.strip().startswith("Parse error")]
    if not lines:
        return True
    return all(NO_MAIN_RE.search(ln) or TOPLEVEL_RE.search(ln) for ln in lines)


def first_line_pin(body: str) -> str | None:
    for line in body.splitlines():
        if not line.strip():
            continue
        m = PIN_RE.match(line)
        return m.group("pin") if m else None
    return None


def check(block: Block, marker: str, python: str) -> Result:
    stem = re.sub(r"[^A-Za-z0-9]+", "_", f"{block.source}_{block.line}")

    if marker == "UNTAGGED":
        return Result(
            block,
            marker,
            False,
            "an untagged fence holds Saw code — tag it "
            "`saw`/`saw-body`/`saw-error`/`saw-fragment`, or `text` if it is not Saw",
        )

    if marker == "saw-fragment":
        return Result(block, marker, True)

    if marker in ("saw", "saw-body"):
        text = block.body if marker == "saw" else wrap_body(block.body)
        ok, out = compile_source(text, stem, python)
        if ICE_RE.search(out):
            return Result(block, marker, False, "the compiler crashed:\n" + indent_out(out))
        if ok:
            return Result(block, marker, True)
        return Result(block, marker, False, "does not compile:\n" + indent_out(out))

    # saw-error
    pin = first_line_pin(block.body)
    if pin is None:
        return Result(
            block,
            marker,
            False,
            "a `saw-error` block needs `// error-contains: <substring>` on its "
            "first line — without it the marker passes on `no main` alone",
        )
    shapes = [("as-is", block.body), ("wrapped", wrap_body(block.body))]
    first_out = ""
    for shape, text in shapes:
        ok, out = compile_source(text, stem, python)
        if shape == "as-is":
            first_out = out
        if ICE_RE.search(out):
            return Result(block, marker, False, "the compiler crashed:\n" + indent_out(out), shape)
        if ok:
            if shape == "as-is":
                return Result(
                    block, marker, False,
                    "marked `saw-error` but the compiler ACCEPTED it", shape,
                )
            break  # the wrap compiling says nothing; the as-is refusal is the subject
        if pin in out:
            return Result(block, marker, True, "", shape)
        if not vacuous(out):
            break  # a real diagnostic that is not the pinned one: report it
    return Result(
        block,
        marker,
        False,
        f"the pinned text is not in the diagnostics.\n  pin: {pin}\n"
        + indent_out(first_out),
    )


def indent_out(out: str) -> str:
    lines = [ln for ln in out.splitlines() if ln.strip()][:8]
    return "\n".join("    " + ln for ln in lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="compile the documentation's Saw examples")
    ap.add_argument("--source", action="append", help="check only this source (repeatable)")
    ap.add_argument("--jobs", type=int, default=max(2, (os.cpu_count() or 4) // 2))
    ap.add_argument("-v", "--verbose", action="store_true", help="list every block")
    args = ap.parse_args()

    python = os.environ.get("SAW_PYTHON") or sys.executable

    sources = args.source or SOURCES
    for source in sources:
        if not (REPO / source).exists():
            print(f"docverify: no such source: {source}", file=sys.stderr)
            return 2

    work: list[tuple[Block, str]] = []
    counts: dict[str, SourceCounts] = {s: SourceCounts() for s in sources}
    for source in sources:
        for block in extract(source):
            marker = classify(block)
            if marker is not None:
                work.append((block, marker))

    results: list[Result] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(check, b, m, python) for b, m in work]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    results.sort(key=lambda r: (r.block.source, r.block.line))
    for r in results:
        c = counts[r.block.source]
        if r.marker == "saw-fragment":
            c.exempt += 1
        elif r.marker == "saw-error":
            c.refused += 1
        elif r.marker in ("saw", "saw-body"):
            c.compiled += 1
        if not r.ok:
            c.failures.append(r)
        if args.verbose:
            print(f"{'ok  ' if r.ok else 'FAIL'} {r.block.where:<28} {r.marker}")

    print()
    print(f"{'source':<36} {'compiled':>9} {'refused':>8} {'exempt':>7} {'exempt %':>9}")
    total = SourceCounts()
    for source in sources:
        c = counts[source]
        pct = (100.0 * c.exempt / c.total) if c.total else 0.0
        print(f"{source:<36} {c.compiled:>9} {c.refused:>8} {c.exempt:>7} {pct:>8.1f}%")
        total.compiled += c.compiled
        total.refused += c.refused
        total.exempt += c.exempt
    tpct = (100.0 * total.exempt / total.total) if total.total else 0.0
    print(f"{'TOTAL':<36} {total.compiled:>9} {total.refused:>8} {total.exempt:>7} {tpct:>8.1f}%")

    failures = [r for r in results if not r.ok]
    if failures:
        print()
        for r in failures:
            print(f"FAIL {r.block.where} (```{r.block.info or '<bare>'}, shape {r.shape})")
            print(f"  {r.detail}")
        print(f"\ndocverify: {len(failures)} block(s) failed of {len(results)}")
        return 1

    print(f"\ndocverify: {len(results)} blocks OK "
          f"({total.compiled} compiled, {total.refused} refused, {total.exempt} exempt)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

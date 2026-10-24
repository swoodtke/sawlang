#!/usr/bin/env python3
"""docverify — compile every Saw example the documentation shows (design 262).

Each fenced block in the sources below is held to what its fence info string
claims, checked by sawc's front end through coroutines (`sawc coro --check`,
which needs no `main`). A doc example nothing compiles is as correct as the
last person to read it; this lane is what compiles them.

ENTRY POINTS (brief obligation 1 — this list IS the funnel; adding a fifth
source is editing `SOURCES` and nothing else):

    README.md
    CLAUDE.md
    LANGUAGE_SPEC.md
    .claude/skills/saw-lang/SKILL.md

THE MARKERS:

    ```saw            a complete compilation unit, checked AS WRITTEN. Must
                      SUCCEED: no ERROR line.

    ```saw-body       a statement sequence. The HARNESS hoists the block's
                      top-level declarations and wraps what is left in a
                      synthesized `func main() { }`, so the scaffold never
                      appears in the doc text. Must SUCCEED.

    ```saw-error      a program sawc must REFUSE. Its first line pins the rule,
                      `// error-rule: RULE`, and an optional second line
                      `// error-contains: TEXT` pins part of that diagnostic's
                      message (or its help). Passes when an ERROR line carries
                      the rule and the text, and no ERROR line is a scaffolding
                      fault (`SCAFFOLDING_RULES`) the pin does not name: a demo
                      that refuses for a missing struct or import shows nothing.

    ```saw-pending SL-NNN
                      an example of a feature sawc does not build yet, citing
                      the OPEN issue it waits on. Like an XFAIL it must still
                      fail, and passing breaks the lane. Without a pin, neither
                      shape may compile; with a `saw-error` pin, the pinned
                      diagnostic must not appear yet. A closed or unknown issue
                      fails the lane too.

    ```saw-fragment   deliberately incomplete — an elision, a signature
                      sketch, one half of a multi-file example. EXEMPT from
                      compilation but COUNTED: the per-source exempt fraction
                      is printed on every run, so erosion toward "everything
                      is a fragment" is loud.

An untagged fence holding Saw code is a LANE ERROR: a block nobody classified
is a block nobody checked. Untagged fences holding shell transcripts, output or
grammar sketches are ignored; tag one `text` if the Saw heuristic trips on it.

SHAPES. `saw` and `saw-body` have one shape each. A `saw-error` or
`saw-pending` block is tried as written first, and wrapped as a `saw-body` only
when the as-written diagnostics are VACUOUS: nothing but the parser's
"expected a declaration", which is what a statement at the top level gets
before any check a doc could be demonstrating runs. A parse refusal is reported
by `coro --check` as `resolve.parse-refused`; the harness reads the parser's
own rule and message from `parse --check` in its place.

This lane does not check the spec's std module table.

    tools/docverify.py                 # every source
    tools/docverify.py --source README.md
    tools/docverify.py --jobs 4 -v
    tools/docverify.py --self-test     # tools/test_docverify.py first (the battery's form)
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
sys.path.insert(0, str(REPO / "compiler" / "tools"))
sys.path.insert(0, str(REPO / "tools"))

import build  # noqa: E402
import check_citations  # noqa: E402

# The funnel's entry points. Everything else in this file is generic over them.
SOURCES = [
    "README.md",
    "CLAUDE.md",
    "LANGUAGE_SPEC.md",
    ".claude/skills/saw-lang/SKILL.md",
]

MARKERS = ("saw", "saw-body", "saw-error", "saw-fragment")
PENDING_RE = re.compile(r"^saw-pending\s+(?P<issue>SL-\d+)$")

SCRATCH = REPO / ".build" / "docverify"

RULE_PIN_RE = re.compile(r"^\s*//\s*error-rule:\s*(?P<rule>\S+)\s*$")
TEXT_PIN_RE = re.compile(r"^\s*//\s*error-contains:\s*(?P<text>.+?)\s*$")

# The rules that say an example is missing a declaration or an import it
# needs, rather than anything about the code it shows.
SCAFFOLDING_RULES = ("name.undefined", "name.not-in-prelude")
SCAFFOLDING_PREFIXES = ("import.",)

# A bare fence holding any of these reads as Saw and must be classified.
SAW_HINT_RE = re.compile(
    r"^\s*(func\s+\w|let\s+\w|var\s+\w|struct\s+\w|enum\s+\w|trait\s+\w"
    r"|extension\s+\w|import\s+\w|public\s+|static\s+\w+\s*:"
    r"|match\s+\w|guard\s+let\s|if\s+let\s|print\()",
    re.M,
)

# One diagnostic line of sawc's stage output: KIND, rule, location, message,
# and an optional help column.
DIAG_RE = re.compile(r"^(?P<kind>ERROR|INVARIANT)\t(?P<rule>[^\t]*)\t(?P<loc>[^\t]*)\t"
                     r"(?P<msg>[^\t]*)(?:\t(?P<help>.*))?$")
LINE_RE = re.compile(r"(?:^|:)(?P<line>\d+):\d+$")

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
class Diagnostic:
    kind: str  # ERROR or INVARIANT
    rule: str
    line: int | None
    message: str
    help: str = ""

    def __str__(self) -> str:
        at = f"@{self.line}" if self.line is not None else ""
        return f"{self.kind} {self.rule}{at}: {self.message}"


@dataclass
class Outcome:
    """One `coro --check` of one shape."""
    accepted: bool
    diagnostics: list[Diagnostic]
    output: str
    crashed: bool = False


@dataclass
class Pin:
    rule: str | None
    text: str | None

    def matches(self, d: Diagnostic) -> bool:
        if d.kind != "ERROR":
            return False
        if self.rule is not None and d.rule != self.rule:
            return False
        return self.text is None or self.text in d.message or self.text in d.help

    def __str__(self) -> str:
        parts = []
        if self.rule is not None:
            parts.append(f"rule {self.rule}")
        if self.text is not None:
            parts.append(f"text {self.text!r}")
        return ", ".join(parts)


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
    pending: int = 0
    exempt: int = 0
    failures: list[Result] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.compiled + self.refused + self.pending + self.exempt


def extract(source: str, text: str | None = None) -> list[Block]:
    """Every fenced block of one source, in document order.

    Fences may be indented; the opening indent is stripped from the body so a
    block nested in a list item compiles as written.
    """
    if text is None:
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
    if PENDING_RE.match(block.info):
        return "saw-pending"
    if block.info.startswith("saw-pending"):
        return "MALFORMED-PENDING"
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


def parse_diagnostics(output: str) -> list[Diagnostic]:
    diags = []
    for raw in output.splitlines():
        m = DIAG_RE.match(raw)
        if not m:
            continue
        lm = LINE_RE.search(m.group("loc"))
        diags.append(Diagnostic(m.group("kind"), m.group("rule"),
                                int(lm.group("line")) if lm else None,
                                m.group("msg"), m.group("help") or ""))
    return diags


def run_sawc(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run([build.SAWC] + args, cwd=REPO, capture_output=True,
                          text=True, timeout=300)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def compile_source(text: str, stem: str) -> Outcome:
    """One `sawc coro --check` over `text`, parse refusals read from the parser."""
    SCRATCH.mkdir(parents=True, exist_ok=True)
    src = SCRATCH / f"{stem}.saw"
    src.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    rel = str(src.relative_to(REPO))
    try:
        code, out = run_sawc(["coro", "--check", rel])
    except subprocess.TimeoutExpired:
        return Outcome(False, [], "docverify: sawc timed out after 300s", crashed=True)
    diags = parse_diagnostics(out)
    if any(d.rule == "resolve.parse-refused" for d in diags):
        _, parsed = run_sawc(["parse", "--check", rel])
        diags = [d for d in diags if d.rule != "resolve.parse-refused"] + parse_diagnostics(parsed)
        out = out + parsed
    # A signal, or an exit that is neither success nor refusal, is a crash.
    crashed = code not in (0, 1) or any(d.kind == "INVARIANT" for d in diags)
    accepted = code == 0 and not diags
    return Outcome(accepted, diags, out, crashed)


def vacuous(outcome: Outcome) -> bool:
    """True when the only diagnostics are the parser's top-level refusal of a
    statement, so the block was never checked for what it shows."""
    errors = [d for d in outcome.diagnostics if d.kind == "ERROR"]
    return bool(errors) and all(
        d.rule == "parse-error" and d.message == "expected a declaration" for d in errors)


def is_scaffolding(d: Diagnostic) -> bool:
    return d.rule in SCAFFOLDING_RULES or d.rule.startswith(SCAFFOLDING_PREFIXES)


def read_pin(body: str) -> Pin | None:
    """The `// error-rule:` / `// error-contains:` pair opening a block.

    The rule line comes first; the text line may follow it, or stand alone in
    a `saw-pending` block whose rule sawc does not have yet.
    """
    lines = [ln for ln in body.splitlines() if ln.strip()][:2]
    rule = text = None
    for ln in lines:
        if rule is None and text is None and (m := RULE_PIN_RE.match(ln)):
            rule = m.group("rule")
            continue
        if text is None and (m := TEXT_PIN_RE.match(ln)):
            text = m.group("text")
            continue
        break
    if rule is None and text is None:
        return None
    return Pin(rule, text)


def judged_shape(block: Block, stem: str) -> tuple[str, Outcome, Outcome]:
    """The shape a refusal is judged in: as written, or wrapped when the
    as-written diagnostics are vacuous. Returns (shape, its outcome, as-is)."""
    asis = compile_source(block.body, stem)
    if asis.crashed or not vacuous(asis):
        return "as-is", asis, asis
    return "wrapped", compile_source(wrap_body(block.body), stem + "_wrapped"), asis


def issue_problem(info: str) -> str | None:
    """Why a `saw-pending` citation is not an open issue, or None if it is."""
    ident = PENDING_RE.match(info).group("issue")
    status = check_citations.issue_status(ident)
    if status == "open":
        return None
    if status is None:
        return f"cites {ident}, which has no file in .sawtracker/issues/ (fetch, or fix the id)"
    return f"cites {ident}, which is {status}: a pending block cites an OPEN issue"


def check(block: Block, marker: str) -> Result:
    stem = re.sub(r"[^A-Za-z0-9]+", "_", f"{block.source}_{block.line}")

    if marker == "UNTAGGED":
        return Result(block, marker, False,
                      "an untagged fence holds Saw code — tag it `saw`/`saw-body`/"
                      "`saw-error`/`saw-pending SL-NNN`/`saw-fragment`, or `text` if it is not Saw")
    if marker == "MALFORMED-PENDING":
        return Result(block, marker, False,
                      f"`{block.info}`: the marker is `saw-pending SL-NNN`, one issue id")
    if marker == "saw-fragment":
        return Result(block, marker, True)

    if marker in ("saw", "saw-body"):
        text = block.body if marker == "saw" else wrap_body(block.body)
        out = compile_source(text, stem)
        if out.crashed:
            return Result(block, marker, False, "the compiler crashed:\n" + indent_out(out.output))
        if out.accepted:
            return Result(block, marker, True)
        return Result(block, marker, False, "does not compile:\n" + indent_out(out.output))

    pin = read_pin(block.body)
    if marker == "saw-pending":
        return check_pending(block, pin, stem)

    # saw-error
    if pin is None or pin.rule is None:
        return Result(block, marker, False,
                      "a `saw-error` block opens with `// error-rule: RULE` (and optionally "
                      "`// error-contains: TEXT` on the next line)")
    shape, out, asis = judged_shape(block, stem)
    if asis.accepted:
        return Result(block, marker, False, "marked `saw-error` but sawc ACCEPTED it", "as-is")
    if out.crashed:
        return Result(block, marker, False, "the compiler crashed:\n" + indent_out(out.output), shape)
    if out.accepted:
        return Result(block, marker, False,
                      "refused only as a top-level statement; the wrapped body compiles", shape)
    if not any(pin.matches(d) for d in out.diagnostics):
        return Result(block, marker, False,
                      f"the pin is not in the diagnostics.\n  pin: {pin}\n" + indent_diags(out), shape)
    noise = [d for d in out.diagnostics if is_scaffolding(d) and d.rule != pin.rule]
    if noise:
        return Result(block, marker, False,
                      "a scaffolding error sits beside the pin; declare or import what the "
                      "example needs:\n" + "\n".join("    " + str(d) for d in noise[:8]), shape)
    return Result(block, marker, True, "", shape)


def check_pending(block: Block, pin: Pin | None, stem: str) -> Result:
    marker = "saw-pending"
    problem = issue_problem(block.info)
    if problem:
        return Result(block, marker, False, problem)
    if pin is None:
        asis = compile_source(block.body, stem)
        wrapped = compile_source(wrap_body(block.body), stem + "_wrapped")
        for shape, out in (("as-is", asis), ("wrapped", wrapped)):
            if out.crashed:
                return Result(block, marker, False, "the compiler crashed:\n" + indent_out(out.output), shape)
            if out.accepted:
                return Result(block, marker, False,
                              f"pending, but it compiles {shape}: mark it `saw`/`saw-body` "
                              "in the landing that closes the issue", shape)
        return Result(block, marker, True)
    shape, out, _ = judged_shape(block, stem)
    if out.crashed:
        return Result(block, marker, False, "the compiler crashed:\n" + indent_out(out.output), shape)
    if any(pin.matches(d) for d in out.diagnostics):
        return Result(block, marker, False,
                      f"pending, but sawc reports the pinned diagnostic ({pin}): mark it "
                      "`saw-error` in the landing that closes the issue", shape)
    return Result(block, marker, True, "", shape)


def indent_out(out: str) -> str:
    lines = [ln for ln in out.splitlines() if ln.strip()][:8]
    return "\n".join("    " + ln for ln in lines)


def indent_diags(out: Outcome) -> str:
    if not out.diagnostics:
        return "    (no diagnostics)"
    return "\n".join("    " + str(d) for d in out.diagnostics[:8])


def ensure_sawc() -> bool:
    """Builds sawc unless a runner above this process chose the binary."""
    if build.handed_down():
        return True
    ok, output = build.build_sawc()
    if not ok:
        print(output)
        print("docverify: sawc did not build")
    return ok


def self_test() -> bool:
    import unittest
    import test_docverify
    suite = unittest.defaultTestLoader.loadTestsFromModule(test_docverify)
    return unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful()


def main() -> int:
    ap = argparse.ArgumentParser(description="compile the documentation's Saw examples")
    ap.add_argument("--source", action="append", help="check only this source (repeatable)")
    ap.add_argument("--jobs", type=int, default=max(2, (os.cpu_count() or 4) // 2))
    ap.add_argument("-v", "--verbose", action="store_true", help="list every block")
    ap.add_argument("--self-test", action="store_true",
                    help="run tools/test_docverify.py's checks of the mechanics first")
    args = ap.parse_args()

    sources = args.source or SOURCES
    for source in sources:
        if not (REPO / source).exists():
            print(f"docverify: no such source: {source}", file=sys.stderr)
            return 2
    if not ensure_sawc():
        return 1
    if args.self_test and not self_test():
        print("docverify: the self-test failed")
        return 1

    work: list[tuple[Block, str]] = []
    counts: dict[str, SourceCounts] = {s: SourceCounts() for s in sources}
    for source in sources:
        for block in extract(source):
            marker = classify(block)
            if marker is not None:
                work.append((block, marker))

    results: list[Result] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(check, b, m) for b, m in work]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    results.sort(key=lambda r: (r.block.source, r.block.line))
    for r in results:
        c = counts[r.block.source]
        if r.marker == "saw-fragment":
            c.exempt += 1
        elif r.marker == "saw-error":
            c.refused += 1
        elif r.marker == "saw-pending":
            c.pending += 1
        elif r.marker in ("saw", "saw-body"):
            c.compiled += 1
        if not r.ok:
            c.failures.append(r)
        if args.verbose:
            print(f"{'ok  ' if r.ok else 'FAIL'} {r.block.where:<28} {r.marker}")

    print()
    print(f"{'source':<36} {'compiled':>9} {'refused':>8} {'pending':>8} {'exempt':>7} {'exempt %':>9}")
    total = SourceCounts()
    for source in sources:
        c = counts[source]
        pct = (100.0 * c.exempt / c.total) if c.total else 0.0
        print(f"{source:<36} {c.compiled:>9} {c.refused:>8} {c.pending:>8} {c.exempt:>7} {pct:>8.1f}%")
        total.compiled += c.compiled
        total.refused += c.refused
        total.pending += c.pending
        total.exempt += c.exempt
    tpct = (100.0 * total.exempt / total.total) if total.total else 0.0
    print(f"{'TOTAL':<36} {total.compiled:>9} {total.refused:>8} {total.pending:>8} "
          f"{total.exempt:>7} {tpct:>8.1f}%")

    failures = [r for r in results if not r.ok]
    if failures:
        print()
        for r in failures:
            print(f"FAIL {r.block.where} (```{r.block.info or '<bare>'}, shape {r.shape})")
            print(f"  {r.detail}")
        print(f"\ndocverify: {len(failures)} block(s) failed of {len(results)}")
        return 1

    print(f"\ndocverify: {len(results)} blocks OK ({total.compiled} compiled, "
          f"{total.refused} refused, {total.pending} pending, {total.exempt} exempt)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

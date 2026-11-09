#!/usr/bin/env python3
"""Lints the mechanically detectable code-comment rules (CLAUDE.md "Code comments").

Checks dates, history words, design/issue references (more than one per
comment, or one that is not a trailing pointer), and line numbers or counts,
in every tracked .saw/.c/.h/.py/.sh comment and Python docstring.
Today's findings are recorded by file, rule and comment text in
commentlint_baseline.tsv, which may only shrink: a new finding fails, and so
does a fixed one until --write-baseline lowers the count. Editing a baselined
comment changes its text, so the edit must bring it fully under the rules.
The step also compares the baseline with the base revision's copy, so a hand
edit cannot raise it. A justified false positive is listed in
commentlint_allow.tsv with its reason; a row matching nothing fails.
"""

import ast
import io
import os
import re
import subprocess
import sys
import tokenize
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASELINE = REPO / "tools" / "commentlint_baseline.tsv"
ALLOWLIST = REPO / "tools" / "commentlint_allow.tsv"

# (path regex, why it is scanned). Every pattern must match at least one file.
INCLUDE = (
    (r"^compiler/[^/]+/src/.*\.saw$", "each compiler stage's Saw source"),
    (r"^compiler/driver/.*\.saw$", "the sawc driver's Saw source"),
    (r"^std/.*\.saw$", "the standard library"),
    (r"^runtime/.*\.saw$", "the runtime's Saw-authored seam bodies"),
    (r"^blade/src/.*\.saw$", "the Blade package manager"),
    (r"^libs/[^/]+/src/.*\.saw$", "the real library packages"),
    (r"^runtime/.*\.(c|h)$", "the runtime's C shim"),
    (r"^(tools|compiler/tools|compiler/tests)/.*\.py$", "the Python tooling and test runners"),
    (r"^tools/.*\.sh$", "the shell tooling"),
    (r"^build\.sh$", "the gate's entry point"),
)

# Prefixes that stay out even when INCLUDE matches.
FROZEN_PREFIXES = ("prototypes/", "devtools/", "examples/", "compiler/prototypes/")

RULES = (
    "date",
    "history",
    "refs.count",
    "refs.position",
    "numbers.line",
    "numbers.count",
)

MONTH = (
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
)
DATE_RES = (
    re.compile(r"\b" + MONTH + r"\.? \d{1,2}\b"),
    re.compile(r"(?<![+\w])20[2-3]\d\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
)
HISTORY_RES = (
    re.compile(
        r"\bpreviously\b|\bformerly\b|\bretired\b|\bonce was\b|"
        r"\bwas renamed\b|\brenamed from\b|\bbefore (DF|SL)-\d|\bruled by\b",
        re.I,
    ),
    re.compile(
        r"(?<!\bis )(?<!\bare )(?<!\bbe )(?<!\bbeen )(?<!\bbeing )"
        r"(?<!\bget )(?<!\bgets )(?<!\bgot )(?<!\bwas )\bused to\b",
        re.I,
    ),
    re.compile(r"\bRULED\b"),
)
REF_RE = re.compile(
    r"\bdesign \d+|\bDesign \d+|\bDF-\d+[a-z]*\b|\bSL-\d+\b|\bSO-\d+\b|"
    r"\bST-\d+\b|\bSL:[a-z][a-z-]*"
)
STAGE0_RE = re.compile(r"Stage 0 workaround \(SL:hazards ")
LINE_NUM_RES = (
    re.compile(r"\blines? [1-9]\d*\b"),
    re.compile(r"\b[\w./-]+\.(saw|py|c|h|md|sh|tsv):\d+\b"),
)
COUNT_RES = (
    re.compile(r"\b\d+ (sites|call sites|callers|occurrences|uses)\b"),
    re.compile(r"\b\d+(\.\d+)?%"),
)
BACKTICK_RE = re.compile(r"`[^`]*`")
TAIL_RE = re.compile(r"^[.,;:]*\s*$")


class ScanError(Exception):
    pass


class Block:
    """A maximal run of comment lines of one kind: `lines` is [(lineno, text)]."""

    def __init__(self, kind, lines):
        self.kind = kind
        self.lines = lines


# ---- file selection ----------------------------------------------------


def tracked_files():
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    return out.splitlines()


def select_files(tracked):
    """Returns the scanned paths; raises ScanError when a pattern matches nothing."""
    chosen = set()
    for pattern, why in INCLUDE:
        rx = re.compile(pattern)
        hit = [p for p in tracked if rx.search(p) and not excluded(p)]
        if not hit:
            raise ScanError(f"include pattern {pattern!r} ({why}) matches no file")
        chosen.update(hit)
    return sorted(chosen)


def excluded(path):
    if path.startswith(FROZEN_PREFIXES):
        return True
    if path.endswith(".saw") and "tests" in path.split("/")[:-1]:
        return True
    if path.startswith("compiler/tests/grammar/") and not path.endswith(".py"):
        return True
    return False


# ---- comment extraction ------------------------------------------------


def group_lines(lines):
    """Groups [(lineno, kind, trailing, text)] into blocks of adjacent same-kind lines."""
    blocks = []
    cur = None
    last_no = None
    for no, kind, trailing, text in lines:
        if (
            cur is not None
            and not trailing
            and not cur[1]
            and cur[0].kind == kind
            and no == last_no + 1
        ):
            cur[0].lines.append((no, text))
        else:
            cur = (Block(kind, [(no, text)]), trailing)
            blocks.append(cur[0])
        last_no = no
    return blocks


def slash_comment(rest):
    """Splits the text after `//` into (kind, text)."""
    if rest.startswith("/") and not rest.startswith("//"):
        return "doc", rest[1:]
    if rest.startswith("!"):
        return "inner", rest[1:]
    return "plain", rest


def extract_slash(text, path, c_like):
    """Scans .saw/.c/.h source by character state: code, strings, comments."""
    out = []
    lineno = 1
    i = 0
    n = len(text)
    line_has_code = False
    while i < n:
        ch = text[i]
        if ch == "\n":
            lineno += 1
            line_has_code = False
            i += 1
        elif ch == '"':
            line_has_code = True
            i += 1
            while True:
                if i >= n or text[i] == "\n":
                    raise ScanError(f"{path}:{lineno}: unterminated or multi-line string")
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == '"':
                    i += 1
                    break
                i += 1
        elif c_like and ch == "'":
            line_has_code = True
            i += 1
            while i < n and text[i] != "'" and text[i] != "\n":
                i += 2 if text[i] == "\\" else 1
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            end = n if end < 0 else end
            kind, body = slash_comment(text[i + 2 : end])
            out.append((lineno, kind, line_has_code, body))
            i = end
        elif text.startswith("/*", i):
            if not c_like:
                raise ScanError(f"{path}:{lineno}: block comment in a Saw file")
            end = text.find("*/", i + 2)
            if end < 0:
                raise ScanError(f"{path}:{lineno}: unterminated block comment")
            body = text[i + 2 : end]
            for k, part in enumerate(body.split("\n")):
                part = part.strip()
                if part.startswith("*"):
                    part = part[1:]
                out.append((lineno + k, "block", line_has_code and k == 0, part))
            lineno += body.count("\n")
            i = end + 2
            line_has_code = True
        else:
            if not ch.isspace():
                line_has_code = True
            i += 1
    return group_lines(out)


def extract_shell(text, path):
    out = []
    for no, line in enumerate(text.split("\n"), 1):
        if no == 1 and line.startswith("#!"):
            continue
        quote = None
        i = 0
        while i < len(line):
            ch = line[i]
            if quote == '"' and ch == "\\":
                i += 2
                continue
            if quote:
                if ch == quote:
                    quote = None
            elif ch in "'\"":
                quote = ch
            elif ch == "\\":
                i += 2
                continue
            elif ch == "#" and (i == 0 or line[i - 1].isspace()):
                out.append((no, "hash", bool(line[:i].strip()), line[i + 1 :]))
                break
            i += 1
    return group_lines(out)


OPEN_QUOTE_RE = re.compile(r"""^[rRuUbBfF]*(\"\"\"|'''|"|')""")
CLOSE_QUOTE_RE = re.compile(r"""(\"\"\"|'''|"|')$""")


def extract_python(text, path):
    out = []
    lines = text.split("\n")
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type != tokenize.COMMENT:
            continue
        no = tok.start[0]
        if no == 1 and tok.string.startswith("#!"):
            continue
        out.append((no, "hash", bool(tok.line[: tok.start[1]].strip()), tok.string[1:]))
    blocks = group_lines(out)
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.body:
            continue
        first = node.body[0]
        if not (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            continue
        start, end = first.lineno, first.end_lineno
        body = []
        for no in range(start, end + 1):
            line = lines[no - 1].strip()
            if no == start:
                line = OPEN_QUOTE_RE.sub("", line, count=1)
            if no == end:
                line = CLOSE_QUOTE_RE.sub("", line, count=1)
            body.append((no, line))
        blocks.append(Block("docstring", body))
    return blocks


def extract(path, text):
    if path.endswith(".saw"):
        return extract_slash(text, path, False)
    if path.endswith((".c", ".h")):
        return extract_slash(text, path, True)
    if path.endswith(".py"):
        return extract_python(text, path)
    return extract_shell(text, path)


# ---- the rules ---------------------------------------------------------


def refs_in(clean):
    return [m for m in REF_RE.finditer(clean)]


def is_trailing_pointer(clean, pos):
    """True when `pos` sits in a parenthesised group that ends the line."""
    depth = 0
    open_at = None
    for k in range(pos - 1, -1, -1):
        if clean[k] == ")":
            depth += 1
        elif clean[k] == "(":
            if depth == 0:
                open_at = k
                break
            depth -= 1
    if open_at is None:
        return False
    depth = 0
    for k in range(open_at, len(clean)):
        if clean[k] == "(":
            depth += 1
        elif clean[k] == ")":
            depth -= 1
            if depth == 0:
                return bool(TAIL_RE.match(clean[k + 1 :]))
    return False


def check_blocks(blocks):
    """Returns [(lineno, rule, text)] for every finding in the blocks."""
    found = []
    for block in blocks:
        seen_refs = 0
        for no, raw in block.lines:
            clean = BACKTICK_RE.sub("", raw)
            shown = raw.strip()
            for rx in DATE_RES:
                if rx.search(clean):
                    found.append((no, "date", shown))
                    break
            for rx in HISTORY_RES:
                if rx.search(clean):
                    found.append((no, "history", shown))
                    break
            if not STAGE0_RE.search(clean):
                for m in refs_in(clean):
                    seen_refs += 1
                    if seen_refs == 2:
                        found.append((no, "refs.count", shown))
                    if not is_trailing_pointer(clean, m.start()):
                        found.append((no, "refs.position", shown))
            if any(rx.search(clean) for rx in LINE_NUM_RES):
                found.append((no, "numbers.line", shown))
            if any(rx.search(clean) for rx in COUNT_RES):
                found.append((no, "numbers.count", shown))
    found.sort(key=lambda f: (f[0], RULES.index(f[1])))
    return found


# ---- allowlist and baseline -------------------------------------------


def parse_allowlist(text):
    """Returns (rows, errors); a row is (rownum, path, rule, text, reason)."""
    rows, errors = [], []
    for no, line in enumerate(text.split("\n"), 1):
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 4 or not all(p.strip() for p in parts):
            errors.append(f"commentlint: allowlist line {no} is not PATH<TAB>RULE<TAB>TEXT<TAB>REASON")
            continue
        rows.append((no, *parts))
    return rows, errors


def apply_allowlist(findings, rows):
    """findings: {path: [(line, rule, text)]}. Returns (kept, stale-row errors)."""
    used = set()
    kept = {}
    for path, items in findings.items():
        keep = []
        for no, rule, text in items:
            hit = None
            for row in rows:
                if row[1] == path and row[2] == rule and row[3] in text:
                    hit = row
                    break
            if hit:
                used.add(hit[0])
            else:
                keep.append((no, rule, text))
        if keep:
            kept[path] = keep
    stale = [
        f"commentlint: allowlist row {r[0]} matches nothing"
        for r in rows
        if r[0] not in used
    ]
    return kept, stale


def parse_baseline(text):
    base = {}
    for line in text.split("\n"):
        if not line.strip() or line.startswith("#"):
            continue
        path, rule, count, text = line.split("\t")
        base[(path, rule, text)] = int(count)
    return base


def normalise(text):
    return " ".join(text.split())


def count_findings(findings):
    """Counts findings by (path, rule, normalised comment text)."""
    counts = defaultdict(int)
    for path, items in findings.items():
        for _, rule, text in items:
            counts[(path, rule, normalise(text))] += 1
    return dict(counts)


def compare_baseline(current, baseline, findings):
    """The pure check: failure strings for every key off its baseline count."""
    failures = []
    hint = False
    for key in sorted(set(current) | set(baseline)):
        cur, base = current.get(key, 0), baseline.get(key, 0)
        path, rule, text = key
        if cur > base:
            for no, r, t in findings.get(path, []):
                if r == rule and normalise(t) == text:
                    failures.append(f"commentlint: {path}:{no}: {rule}: {t}")
            hint = True
        elif cur < base:
            failures.append(
                f"commentlint: {path} has {cur} {rule} finding(s) for \"{text}\", "
                f"the baseline records {base}: run tools/commentlint.py --write-baseline"
            )
    if hint:
        failures.append(
            "commentlint: reword the comment, or justify it in tools/commentlint_allow.tsv"
        )
    return failures


def rise_refusals(current, baseline):
    """The keys --write-baseline would raise, as messages."""
    return [
        f"commentlint: {p} {r} \"{t}\" would rise from {baseline.get((p, r, t), 0)} to {c}"
        for (p, r, t), c in sorted(current.items())
        if c > baseline.get((p, r, t), 0)
    ]


def base_rise_failures(base_rows, working_rows):
    """Failures for every key whose count in the working baseline exceeds the base's."""
    return [
        f"commentlint: the baseline rises at {p} {r} \"{t}\"; a new exception goes "
        "in tools/commentlint_allow.tsv with its reason"
        for (p, r, t), c in sorted(working_rows.items())
        if c > base_rows.get((p, r, t), 0)
    ]


def rise_check(base_text, working_rows):
    """Returns (failures, skipped) comparing the baseline with the base revision's text."""
    if base_text is None:
        return [], 1
    try:
        base_rows = parse_baseline(base_text)
    except ValueError:
        return [], 1
    return base_rise_failures(base_rows, working_rows), 0


def base_baseline_text():
    """The baseline file at the base revision, or None when it cannot be found."""
    rev = os.environ.get("SAW_GATE_BASE")
    if not rev:
        merged = subprocess.run(
            ["git", "merge-base", "HEAD", "main"], cwd=REPO, capture_output=True, text=True
        )
        if merged.returncode != 0:
            return None
        rev = merged.stdout.strip()
    shown = subprocess.run(
        ["git", "show", f"{rev}:tools/commentlint_baseline.tsv"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    return shown.stdout if shown.returncode == 0 else None


def baseline_text(current):
    head = (
        "# Comment-lint baseline: one row per distinct finding, PATH RULE COUNT TEXT.\n"
        "# Counts may only fall; tools/commentlint.py --write-baseline lowers them\n"
        "# and refuses a rise, and the step compares this file with the base revision's.\n"
    )
    rows = "".join(f"{p}\t{r}\t{c}\t{t}\n" for (p, r, t), c in sorted(current.items()) if c)
    return head + rows


# ---- driver ------------------------------------------------------------


def scan(tracked=None):
    """Returns (files scanned, {path: [(line, rule, text)]}) before the allowlist."""
    files = select_files(tracked_files() if tracked is None else tracked)
    findings = {}
    for path in files:
        text = (REPO / path).read_text(encoding="utf-8", errors="replace")
        found = check_blocks(extract(path, text))
        if found:
            findings[path] = found
    return files, findings


def load_allowlist():
    if not ALLOWLIST.exists():
        return [], []
    return parse_allowlist(ALLOWLIST.read_text(encoding="utf-8"))


def run():
    """Returns (failures, counts) for run.py: the baseline check."""
    try:
        files, findings = scan()
    except (ScanError, SyntaxError, tokenize.TokenError) as e:
        return [f"commentlint: {e}"], {}
    rows, errors = load_allowlist()
    findings, stale = apply_allowlist(findings, rows)
    current = count_findings(findings)
    baseline = parse_baseline(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    rises, skipped = rise_check(base_baseline_text(), baseline)
    failures = errors + stale + compare_baseline(current, baseline, findings) + rises
    counts = {
        "comment findings": sum(current.values()),
        "comment files scanned": len(files),
    }
    if skipped:
        counts["comment baseline rise check skipped"] = skipped
    return failures, counts


def main(argv):
    args = argv[1:]
    if "--write-baseline" in args:
        try:
            _, findings = scan()
        except (ScanError, SyntaxError, tokenize.TokenError) as e:
            print(f"commentlint: {e}")
            return 1
        rows, _ = load_allowlist()
        findings, _ = apply_allowlist(findings, rows)
        current = count_findings(findings)
        if BASELINE.exists():
            refused = rise_refusals(current, parse_baseline(BASELINE.read_text(encoding="utf-8")))
            if refused:
                print("\n".join(refused))
                return 1
        BASELINE.write_text(baseline_text(current), encoding="utf-8")
        print(f"commentlint: wrote {len(current)} baseline rows, {sum(current.values())} findings")
        return 0
    if "--all" in args:
        only = None
        if "--rule" in args:
            only = args[args.index("--rule") + 1]
        try:
            files, findings = scan()
        except (ScanError, SyntaxError, tokenize.TokenError) as e:
            print(f"commentlint: {e}")
            return 1
        rows, _ = load_allowlist()
        findings, _ = apply_allowlist(findings, rows)
        per_rule = defaultdict(int)
        for path in sorted(findings):
            for no, rule, text in findings[path]:
                if only and rule != only:
                    continue
                per_rule[rule] += 1
                print(f"{path}:{no}: {rule}: {text}")
        for rule in RULES:
            if not only or rule == only:
                print(f"{rule}: {per_rule[rule]}")
        print(f"files scanned: {len(files)}")
        return 0
    failures, counts = run()
    if failures:
        print("\n".join(failures))
        return 1
    print(
        f"commentlint: ok, {counts['comment findings']} baselined finding(s) "
        f"in {counts['comment files scanned']} files"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

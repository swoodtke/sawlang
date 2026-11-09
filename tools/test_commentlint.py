#!/usr/bin/env python3
"""Self-test for commentlint.py: each rule and exemption, the baseline and the allowlist."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import commentlint as cl  # noqa: E402


def findings_of(path, text):
    return [(no, rule) for no, rule, _ in cl.check_blocks(cl.extract(path, text))]


# (name, path, source, expected [(line, rule)])
CASES = [
    ("date month day", "a.saw", "// shipped Aug 19\n", [(1, "date")]),
    ("date year", "a.saw", "// in 2026 we\n", [(1, "date")]),
    ("date iso", "a.saw", "// on 2026-09-01 we\n", [(1, "date")]),
    ("date code point", "a.saw", "// U+2028 and U+2029 end a line\n", []),
    ("numbers line zero", "a.saw", "// at line 0 of the dump\n", []),
    ("numbers places dropped", "a.saw", "// as Stage 0 places it\n", []),
    ("history no longer dropped", "a.saw", "// no longer held here\n", []),
    ("date lowercase may", "a.saw", "// you may 5 times\n", []),
    ("date backticked", "a.saw", "// the `Aug 19` literal\n", []),
    ("history previously", "a.saw", "// previously a loop\n", [(1, "history")]),
    ("history retired", "a.saw", "// it is retired here\n", [(1, "history")]),
    ("history RULED", "a.saw", "// RULED here\n", [(1, "history")]),
    ("history used to", "a.saw", "// it used to loop\n", [(1, "history")]),
    ("history is used to", "a.saw", "// the flag is used to loop\n", []),
    ("history was used to", "a.saw", "// it was used to loop\n", []),
    ("ref trailing", "a.saw", "// does a thing (design 262).\n", []),
    ("ref trailing no period", "a.saw", "// does a thing (SL-12)\n", []),
    ("ref position mid", "a.saw", "// does a thing (design 238 unit 3), because x\n", [(1, "refs.position")]),
    ("ref position bare", "a.saw", "// design 238 splits it\n", [(1, "refs.position")]),
    ("ref stage0 marker", "a.saw", "// Stage 0 workaround (SL:hazards h1): canonical: x\n", []),
    (
        "refs.count two in one block",
        "a.saw",
        "// first (design 1)\n// second (DF-2a).\n",
        [(2, "refs.count")],
    ),
    (
        "refs.count split by code",
        "a.saw",
        "// first (design 1)\nlet x = 1\n// second (DF-2a).\n",
        [],
    ),
    ("numbers line", "a.saw", "// see line 40 here\n", [(1, "numbers.line")]),
    ("numbers file:line", "a.saw", "// see foo.py:12 here\n", [(1, "numbers.line")]),
    ("numbers sites", "a.saw", "// 12 call sites use it\n", [(1, "numbers.count")]),
    ("numbers percent", "a.saw", "// about 40% faster\n", [(1, "numbers.count")]),
    ("saw string url", "a.saw", 'let u = "https://x" // fine\n', []),
    ("saw string url then date", "a.saw", 'let u = "https://x" // Aug 19\n', [(1, "date")]),
    ("c string slashes", "a.c", 'char *s = "a // Aug 19";\n', []),
    ("c char literal", "a.c", "char q = '\"'; // 2026\n", [(1, "date")]),
    ("c block comment", "a.c", "/* in 2026 */\nint x;\n", [(1, "date")]),
    ("doc comment kind", "a.saw", "/// in 2026\n// in 2026\n", [(1, "date"), (2, "date")]),
    (
        "doc and plain are two blocks",
        "a.saw",
        "/// first (design 1)\n// second (design 2).\n",
        [],
    ),
    ("py hash", "a.py", "x = 1  # since Aug 19\n", [(1, "date")]),
    ("py string hash", "a.py", 'x = "# Aug 19"\n', []),
    ("py shebang", "a.py", "#!/usr/bin/env python3\nx = 1\n", []),
    (
        "py docstring one block",
        "a.py",
        'def f():\n    """Summary (design 1).\n\n    More (design 2).\n    """\n',
        [(4, "refs.count")],
    ),
    ("py module docstring", "a.py", '"""In 2026 only."""\n', [(1, "date")]),
    ("sh comment", "a.sh", "#!/bin/sh\n# in 2026\n", [(2, "date")]),
    ("sh trailing", "a.sh", "ls # in 2026\n", [(1, "date")]),
    ("sh quoted hash", "a.sh", "echo 'a # 2026'\n", []),
    ("sh dollar hash", "a.sh", 'echo "$#" $# 2026\n', []),
]


def check_cases():
    failures = []
    for name, path, src, want in CASES:
        got = findings_of(path, src)
        if got != want:
            failures.append(f"case {name!r}: expected {want}, got {got}")
    return failures


def check_scan_errors():
    failures = []
    for name, path, src in (
        ("saw block comment", "a.saw", "/* x */\n"),
        ("saw multi-line string", "a.saw", 'let s = "a\nb"\n'),
    ):
        try:
            cl.extract(path, src)
            failures.append(f"case {name!r}: expected ScanError")
        except cl.ScanError:
            pass
    return failures


def check_baseline():
    failures = []
    f = {"p": [(3, "date", "x  y")]}
    k = ("p", "date", "x y")
    if cl.compare_baseline({k: 1}, {k: 1}, f):
        failures.append("baseline: an equal count must pass")
    rise = cl.compare_baseline({k: 1}, {}, f)
    if not any("p:3: date: x  y" in m for m in rise) or not any("commentlint_allow.tsv" in m for m in rise):
        failures.append(f"baseline: a rise must list the finding and the hint, got {rise}")
    fall = cl.compare_baseline({}, {k: 2}, {})
    if len(fall) != 1 or "--write-baseline" not in fall[0] or "records 2" not in fall[0]:
        failures.append(f"baseline: a fall must name --write-baseline, got {fall}")
    swap = cl.compare_baseline(
        {("p", "date", "new"): 1},
        {("p", "date", "old"): 1},
        {"p": [(9, "date", "new")]},
    )
    if not any("p:9: date: new" in m for m in swap) or not any("--write-baseline" in m for m in swap):
        failures.append(f"baseline: a fix and a new finding in one file must both fail, got {swap}")
    if not cl.rise_refusals({k: 2}, {k: 1}):
        failures.append("baseline: --write-baseline must refuse a rise")
    if not cl.rise_refusals({("q", "date", "x"): 1}, {}):
        failures.append("baseline: --write-baseline must refuse a new key")
    if cl.rise_refusals({k: 1}, {k: 2}):
        failures.append("baseline: --write-baseline must accept a fall")
    text = cl.baseline_text({k: 2, ("p", "history", "z"): 0})
    if cl.parse_baseline(text) != {k: 2}:
        failures.append(f"baseline: text round trip gave {cl.parse_baseline(text)}")
    counted = cl.count_findings({"p": [(1, "date", "a   b"), (2, "date", "a b")]})
    if counted != {("p", "date", "a b"): 2}:
        failures.append(f"baseline: whitespace must collapse in the key, got {counted}")
    return failures


def check_base_rise():
    failures = []
    k = ("p", "date", "x")
    base = cl.baseline_text({k: 1})
    raised, skipped = cl.rise_check(base, {k: 2})
    if skipped or len(raised) != 1 or 'rises at p date "x"' not in raised[0] or "commentlint_allow.tsv" not in raised[0]:
        failures.append(f"base rise: a raised row must fail, got {raised} {skipped}")
    added, _ = cl.rise_check(base, {k: 1, ("p", "date", "y"): 1})
    if len(added) != 1:
        failures.append(f"base rise: a new key must fail, got {added}")
    for name, working in (("equal", {k: 1}), ("lower", {}), ("lower count", {k: 0})):
        got, skipped = cl.rise_check(base, working)
        if got or skipped:
            failures.append(f"base rise: an {name} row must pass, got {got} {skipped}")
    got, skipped = cl.rise_check(None, {k: 5})
    if got or skipped != 1:
        failures.append(f"base rise: a missing base must skip visibly, got {got} {skipped}")
    got, skipped = cl.rise_check("p\tdate\t1\n", {k: 5})
    if got or skipped != 1:
        failures.append(f"base rise: an unreadable base must skip visibly, got {got} {skipped}")
    return failures


def check_allowlist():
    failures = []
    rows, errors = cl.parse_allowlist("# header\np\tdate\tAug 19\tquoted data\n")
    if errors or len(rows) != 1:
        failures.append(f"allowlist: a good row must parse, got {rows} {errors}")
    _, errors = cl.parse_allowlist("p\tdate\tAug 19\t\n")
    if not errors:
        failures.append("allowlist: an empty reason must fail")
    found = {"p": [(1, "date", "ships Aug 19 here"), (2, "date", "other 2026")]}
    kept, stale = cl.apply_allowlist(found, rows)
    if kept != {"p": [(2, "date", "other 2026")]} or stale:
        failures.append(f"allowlist: a matching row must suppress only its finding, got {kept} {stale}")
    _, stale = cl.apply_allowlist({"p": [(2, "date", "other 2026")]}, rows)
    if not stale or "row 2 matches nothing" not in stale[0]:
        failures.append(f"allowlist: a stale row must fail, got {stale}")
    return failures


def check_selection():
    failures = []
    try:
        cl.select_files(["std/a.saw"])
        failures.append("selection: an unmatched pattern must raise")
    except cl.ScanError:
        pass
    for path in (
        "examples/x.py",
        "compiler/prototypes/x.py",
        "std/tests/x.saw",
        "compiler/tests/grammar/x.saw",
    ):
        if not cl.excluded(path):
            failures.append(f"selection: {path} must be excluded")
    if cl.excluded("compiler/tests/grammar/lint.py"):
        failures.append("selection: grammar tool scripts stay in")
    return failures


def run():
    failures = (
        check_cases()
        + check_scan_errors()
        + check_baseline()
        + check_base_rise()
        + check_allowlist()
        + check_selection()
    )
    return failures, {"commentlint cases": len(CASES)}


if __name__ == "__main__":
    bad, _ = run()
    for line in bad:
        print(line)
    sys.exit(1 if bad else 0)

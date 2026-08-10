#!/usr/bin/env python3
"""The internal-compiler-error report, as a test (design 192 unit 2).

An ICE is by definition a path no program in the corpus takes, so the suite
cannot exercise the reporting machinery — and until this brief there was very
little to exercise: codegen's ~94 bare raises reached a catch-all that printed
a message with NO location, and the typechecker was not wrapped at all, so an
internal failure there printed a raw Python traceback at the user.

Both halves now report the same way, anchored on a breadcrumb the dispatch
chokepoints stamp. Nothing in a normal build proves that still works — delete
the `self._current_node` line from either dispatch and every test in the tree
still passes — so this injects a failure into each stage and reads the report:

  error: internal compiler error at FILE:LINE:COL (<NodeType>): <message>

Checked per stage: the message is ONE line (no traceback leaks to a user), it
carries the `internal compiler error` prefix, it names the source file, the
line, and the AST node class the compiler was working on, and `SAW_DEBUG=1`
brings the full traceback back for whoever is debugging the compiler.

The injection edits a compiler source file in place and restores it in a
`finally`; it never leaves the tree modified, and it runs sawc in a subprocess
so a crashed compiler cannot take this harness with it.

Run from the repo root:  ./.venv/bin/python tools/test_ice_breadcrumb.py
"""
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAWC = os.path.join(REPO, "sawc", "sawc.py")
PROGRAM = os.path.join(REPO, "examples", "hello.saw")

# One case per compiler stage. `anchor` is the exact line to inject beneath;
# `node` is the AST class the breadcrumb must name when the raise fires there.
CASES = [
    {
        "stage": "typechecker",
        "path": os.path.join("sawc", "typechecker", "expressions.py"),
        "anchor": "    def visit_StringLiteral(self, expr: StringLiteral) -> Optional[SawType]:\n",
        "indent": "        ",
        "node": "StringLiteral",
    },
    {
        "stage": "codegen",
        "path": os.path.join("sawc", "codegen", "core.py"),
        "anchor": "    def visit_StringLiteral(self, expr: StringLiteral):\n",
        "indent": "        ",
        "node": "StringLiteral",
    },
]

MARKER = "saw-ice-breadcrumb-probe"
PATTERN = re.compile(
    r"internal compiler error at (?P<file>[^\s]+?):(?P<line>\d+):(?P<col>\d+) "
    r"\((?P<node>\w+)\): (?P<msg>.*)")


def run_sawc(debug):
    env = dict(os.environ)
    env.pop("SAW_DEBUG", None)
    if debug:
        env["SAW_DEBUG"] = "1"
    out = os.path.join(REPO, ".build", "scratch", "ice_breadcrumb_probe")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    return subprocess.run([sys.executable, SAWC, PROGRAM, "-o", out],
                          capture_output=True, text=True, cwd=REPO, env=env)


def check(case):
    """Inject, compile, restore. Returns a list of failure strings."""
    path = os.path.join(REPO, case["path"])
    with open(path) as f:
        original = f.read()
    if case["anchor"] not in original:
        return [f"{case['stage']}: injection anchor not found in {case['path']} "
                f"— the visitor was renamed; update this test"]

    injected = original.replace(
        case["anchor"],
        case["anchor"] + f'{case["indent"]}raise KeyError("{MARKER}")\n',
        1)
    failures = []
    try:
        with open(path, "w") as f:
            f.write(injected)

        plain = run_sawc(debug=False)
        text = (plain.stdout + plain.stderr).strip()
        lines = [ln for ln in text.splitlines() if ln.strip()]

        if plain.returncode == 0:
            failures.append(f"{case['stage']}: the injected failure did not "
                            f"reach the compiler at all (exit 0) — this test "
                            f"is no longer exercising {case['path']}")
            return failures
        if len(lines) != 1:
            failures.append(f"{case['stage']}: the report is {len(lines)} "
                            f"lines, want exactly 1 (a user must never see a "
                            f"Python traceback):\n{text}")
        m = PATTERN.search(text)
        if m is None:
            failures.append(f"{case['stage']}: no `internal compiler error at "
                            f"FILE:LINE:COL (Node)` breadcrumb in:\n{text}")
        else:
            if not m.group("file").endswith(".saw"):
                failures.append(f"{case['stage']}: breadcrumb file is "
                                f"`{m.group('file')}`, want a .saw source")
            if m.group("line") == "0":
                failures.append(f"{case['stage']}: breadcrumb line is 0 — the "
                                f"node carried no position")
            if m.group("node") != case["node"]:
                failures.append(f"{case['stage']}: breadcrumb names "
                                f"`{m.group('node')}`, want `{case['node']}` "
                                f"(the innermost node being processed)")
            if MARKER not in m.group("msg"):
                failures.append(f"{case['stage']}: the raise's own message is "
                                f"missing from the report: {m.group('msg')}")

        debug_run = run_sawc(debug=True)
        debug_text = debug_run.stdout + debug_run.stderr
        if "Traceback (most recent call last)" not in debug_text:
            failures.append(f"{case['stage']}: SAW_DEBUG=1 printed no Python "
                            f"traceback — the compiler-author path is gone")
    finally:
        with open(path, "w") as f:
            f.write(original)
    return failures


def main() -> int:
    all_failures = []
    for case in CASES:
        failures = check(case)
        all_failures.extend(failures)
        status = "FAIL" if failures else "ok  "
        print(f"  {status} {case['stage']}: breadcrumb + one-line report + "
              f"SAW_DEBUG traceback")

    if all_failures:
        print("\nICE reporting has regressed:")
        for f in all_failures:
            print(f"  - {f}")
        print("\nThe stamp lives in the four dispatch chokepoints "
              "(`_check_expression`, `_check_statement`, `_generate_expression`,"
              "\n`_generate_statement`) and the report in `sawc._ice_location` /"
              " `sawc._report_ice`.")
        return 1
    print(f"ice-breadcrumb: {len(CASES)} stage(s) report cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())

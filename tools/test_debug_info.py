#!/usr/bin/env python3
"""Debug-info (design 69) acceptance test — asserts DWARF metadata presence.

The .saw test runner checks program BEHAVIOR (stdout/panic/errors); it has no
IR-level assertions. This standalone check compiles a small program with
`--emit-ir` and verifies the emitted LLVM IR carries the debug metadata that
DWARF line tables require:

  - module flags "Debug Info Version" / "Dwarf Version"
  - a DICompileUnit registered in !llvm.dbg.cu
  - a DISubprogram for a user function (named by its Saw name)
  - !DILocation records on instructions (line tables), present BOTH before and
    after the O1 pipeline (locations must survive optimization)
  - no DILocation(line: 0) gaps (synthesized-node inheritance works)

Run from the repo root:  ./.venv/bin/python tools/test_debug_info.py
Exit code 0 = pass; nonzero (with a diagnostic) = fail.
"""
import os
import re
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
SAWC = os.path.join(REPO, "sawc", "sawc.py")

PROGRAM = """\
func factorial(n: Int) -> Int {
    if n <= 1 {
        return 1
    }
    n * factorial(n - 1)
}

func main() {
    print(factorial(5))
}
"""


def fail(msg):
    print(f"DEBUG-INFO TEST FAILED: {msg}")
    sys.exit(1)


def emit_ir(src_path, out_base, optimize):
    argv = [PY, SAWC, src_path, "--emit-ir", "-o", out_base]
    if not optimize:
        argv.append("-O0")
    r = subprocess.run(argv, capture_output=True, text=True)
    if r.returncode != 0:
        fail(f"--emit-ir ({'O1' if optimize else 'O0'}) failed:\n"
             + r.stdout + r.stderr)
    with open(out_base + ".ll") as f:
        return f.read()


def check(ir_text, label):
    if '!"Debug Info Version"' not in ir_text:
        fail(f"[{label}] missing 'Debug Info Version' module flag")
    if "!llvm.dbg.cu" not in ir_text:
        fail(f"[{label}] missing !llvm.dbg.cu")
    if "DICompileUnit" not in ir_text:
        fail(f"[{label}] missing DICompileUnit")
    if 'name: "factorial"' not in ir_text:
        fail(f"[{label}] missing DISubprogram for 'factorial'")
    if "!DILocation" not in ir_text:
        fail(f"[{label}] missing !DILocation line-table records")
    # No line-0 gaps in RAW codegen: synthesized nodes must inherit an enclosing
    # line (the design-69 coroutine-line requirement). The O1 pipeline may
    # legitimately introduce line-0 on merged/artificial instructions, so this
    # invariant is only asserted at O0.
    if label == "O0" and re.search(r"DILocation\([^)]*\bline: 0\b", ir_text):
        fail(f"[{label}] found DILocation(line: 0) — a synthesized-node gap")


def main():
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "difactorial.saw")
        with open(src, "w") as f:
            f.write(PROGRAM)
        out = os.path.join(d, "difactorial")

        check(emit_ir(src, out, optimize=False), "O0")
        check(emit_ir(src, out, optimize=True), "O1")

    print("DEBUG-INFO TEST: ok (DICompileUnit + DISubprogram + !DILocation "
          "present at O0 and O1; no line-0 gaps)")


if __name__ == "__main__":
    main()

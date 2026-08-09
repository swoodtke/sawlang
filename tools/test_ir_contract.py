#!/usr/bin/env python3
"""Properties of the emitted IR that no examples test can express (design 187).

These are miscompiles rather than diagnostics, and each is invisible on the path
the suite walks.

CHECKED — the object compile embeds what the hosted compile embeds (DF-158e).
`object_only` used to decide `is_entry`, and `is_entry` is what runs the
whole-program effect fixpoint; without it every callee's `suspends` bit stayed
False, so the coroutine transform's closure walk never reached a spawn root's
nested suspending callees and the call lowered as a direct BLOCKING one. In a
kernel that nested park runs inline, on the only stack there is. The frame set a
program gets is a property of the transform, not of the output shape, so the two
compiles must agree on it exactly. The examples runner cannot see this: it runs
programs, and a program compiled with `-c` is an object file nobody spawns.

Compared at `-O0`. At the default pipeline the whole-program build inlines a
frame's resume method into its one caller and the SYMBOL disappears, which says
nothing about whether the frame was built.

Run from the repo root:  ./.venv/bin/python tools/test_ir_contract.py
Exit code 0 = pass; nonzero (with a diagnostic) = fail.
"""

import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAWC = os.path.join(ROOT, "sawc", "sawc.py")

# Coroutine-shaped programs whose frame set an object compile has to reproduce:
# a spawn root over a two-deep nest, a suspending `main` over a nest, a nested
# suspending METHOD call (the design-84 sub-frame), and a plain two-deep chain.
EMBED_CORPUS = [
    "task_backtrace_nest.saw",
    "async_main_nested_sleep.saw",
    "coro_nested_suspend_method.saw",
    "coro_nested_suspend_two_deep.saw",
]

# A frame's presence is read off the methods the transform synthesizes for it.
_FRAME_RE = re.compile(
    r"__Frame_([A-Za-z0-9_$]+?)___"
    r"(?:state|resume|is_cancelled|wake_reason|bt_desc)")


def _sawc(args):
    proc = subprocess.run([sys.executable, SAWC] + args,
                          capture_output=True, text=True, cwd=ROOT)
    if proc.returncode != 0:
        raise RuntimeError(f"sawc {' '.join(args)} failed:\n"
                           f"{proc.stdout}\n{proc.stderr}")
    return proc.stdout


def _emit_ir(source, extra, tag):
    out = os.path.join(ROOT, ".build", "ircontract", tag)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    _sawc([source, "--emit-ir", "-O0", "-o", out] + extra)
    with open(out + ".ll") as f:
        return f.read()


def check_embedding(failures):
    for name in EMBED_CORPUS:
        source = os.path.join(ROOT, "examples", name)
        if not os.path.exists(source):
            failures.append(f"{name}: missing from examples/")
            continue
        stem = name[:-4]
        hosted = sorted(set(_FRAME_RE.findall(
            _emit_ir(source, [], stem + "_hosted"))))
        obj = sorted(set(_FRAME_RE.findall(
            _emit_ir(source, ["-c"], stem + "_obj"))))
        if hosted != obj:
            missing = [f for f in hosted if f not in obj]
            extra = [f for f in obj if f not in hosted]
            failures.append(
                f"{name}: the `-c` compile does not embed what the hosted "
                f"compile embeds.\n"
                f"      hosted frames: {hosted}\n"
                f"      -c frames:     {obj}\n"
                f"      missing under -c: {missing or 'none'}; "
                f"only under -c: {extra or 'none'}")
        elif not hosted:
            failures.append(
                f"{name}: no coroutine frames at all — the fixture no longer "
                f"exercises the embedding this checks")


def main() -> int:
    failures = []
    check_embedding(failures)

    if failures:
        print("IR contract violations:\n")
        for f in failures:
            print(f"  - {f}\n")
        return 1

    print(f"IR contract: {len(EMBED_CORPUS)} programs embed identically with "
          f"and without -c")
    return 0


if __name__ == "__main__":
    sys.exit(main())

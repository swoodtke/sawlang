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

CHECKED — every `__saw_rt_*` seam the compiler declares has the width rt/ABI.md
gives it, on a 64-bit AND a 32-bit target (DF-158c). The document distinguishes
`word` (pointer-width) from `Int64`, and those two are the same machine type on
every host the suite runs on, so nothing here can be told apart without a
cross-compile — which the suite does not do. An `@export`ed definition UNIFIES
with the compiler's declaration of the same symbol and inherits its type, so a
wrong declaration silently overrode a correct runtime body: riscv32 emitted
`define i32` for the `-> Int64` clock seam while the ABI, std and the body all
said i64, and a whole family of `word` seams came out i64. The define side is
checked too, over a real runtime seam body.

The expected types come from `runtime_abi.abi_signatures()` — the same parse of
rt/ABI.md that `--runtime-provider` checks a runtime's Saw signatures against —
so the compiler's declarations and a runtime's definitions are held to ONE
document.

Run from the repo root:  ./.venv/bin/python tools/test_ir_contract.py
Exit code 0 = pass; nonzero (with a diagnostic) = fail.
"""

import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAWC = os.path.join(ROOT, "sawc", "sawc.py")
sys.path.insert(0, os.path.join(ROOT, "sawc"))

from runtime_abi import abi_signatures  # noqa: E402

# Coroutine-shaped programs whose frame set an object compile has to reproduce:
# a spawn root over a two-deep nest, a suspending `main` over a nest, a nested
# suspending METHOD call (the design-84 sub-frame), and a plain two-deep chain.
EMBED_CORPUS = [
    "task_backtrace_nest.saw",
    "async_main_nested_sleep.saw",
    "coro_nested_suspend_method.saw",
    "coro_nested_suspend_two_deep.saw",
]

# Hosted programs between them reaching the whole io / thread / process seam
# family, so the 64-bit leg has something to check.
SEAM_CORPUS_HOSTED = [
    "net_accept_roundtrip.saw",
    "process_simple.saw",
    "offload_signature_shapes.saw",
]

# A freestanding program that REFERENCES the seams (it prints and allocates), so
# the 32-bit leg is not checking an empty module.
SEAM_SOURCE_RV32 = "freestanding_seams_extern_no_runtime.saw"

# The 32-bit leg. riscv32 is what SOS actually ships on, and `+m,+a,+c` is what
# the part has (design 172: the profile does not imply it, the PART does).
RV32 = ["--freestanding", "--target", "riscv32-unknown-none-elf",
        "--target-features", "+m,+a,+c"]

# A frame's presence is read off the methods the transform synthesizes for it.
_FRAME_RE = re.compile(
    r"__Frame_([A-Za-z0-9_$]+?)___"
    r"(?:state|resume|is_cancelled|wake_reason|bt_desc)")

# llvmlite's unoptimized rendering: `declare external i64 @"name"(i64 %".1")`.
# The head is scanned rather than matched whole — a parameter may itself be a
# function-pointer type (`void (i8*)* %".1"`), whose parentheses no flat regex
# can survive.
_HEAD_RE = re.compile(
    r'^[ \t]*(declare|define)\b(.*?)@"?(__saw_rt_[A-Za-z0-9_]+)"?\(',
    re.MULTILINE)


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


# ------------------------------------------------------------- seam widths

def _llvm_for(abi_class, int_width):
    """The LLVM type an ABI class must lower to at a given platform width."""
    if abi_class in ("void", "noreturn"):
        return "void"
    if abi_class == "word":
        return f"i{int_width}"
    return abi_class          # i64 / i32 / i16 / i8 — fixed on every target


def _normalize(spelling):
    """One LLVM parameter/return spelling from the dump, as a bare type."""
    text = spelling.strip()
    # Drop the parameter's SSA name (`i64 %".1"`) and any leading attributes
    # (`noundef i64`, `nonnull i8*`).
    text = text.split('%')[0].strip()
    for attr in ("noundef", "nonnull", "signext", "zeroext", "readonly",
                 "noalias", "returned", "local_unnamed_addr", "external",
                 "internal", "dso_local"):
        text = re.sub(rf"\b{attr}\b", " ", text)
    text = " ".join(text.split())
    if text.endswith("*") or text == "ptr":
        return "ptr"
    return text


def _split_params(text, start):
    """The comma-separated parameter spellings of the list opening at `start`
    (the index just past `(`), respecting nested parens/brackets."""
    depth = 0
    parts = []
    piece = []
    i = start
    while i < len(text):
        ch = text[i]
        if ch in "([{<":
            depth += 1
        elif ch in ")]}>":
            if ch == ')' and depth == 0:
                break
            depth -= 1
        elif ch == ',' and depth == 0:
            parts.append("".join(piece))
            piece = []
            i += 1
            continue
        piece.append(ch)
        i += 1
    tail = "".join(piece).strip()
    if tail:
        parts.append(tail)
    return [p for p in (p.strip() for p in parts) if p]


def _seam_types(ir_text):
    """`{symbol: (param types, return type)}` for every seam in one dump."""
    found = {}
    for m in _HEAD_RE.finditer(ir_text):
        head, name = m.group(2), m.group(3)
        params = _split_params(ir_text, m.end())
        # A `define` and a `declare` of one symbol carry the same type; keep
        # whichever came first rather than reporting the pair twice.
        found.setdefault(name, (tuple(_normalize(p) for p in params),
                                _normalize(head)))
    return found


def _check_widths(ir_text, int_width, where, failures):
    documented = abi_signatures()
    seen = 0
    for name, (params, ret) in sorted(_seam_types(ir_text).items()):
        expected = documented.get(name)
        if expected is None:
            continue          # undocumented; test_runtime_abi_doc.py owns that
        want_params, want_ret = expected
        seen += 1
        want_ret_llvm = _llvm_for(want_ret, int_width)
        if ret != want_ret_llvm and not (want_ret == "word" and ret == "ptr"):
            failures.append(
                f"{where}: `{name}` returns `{ret}`, but rt/ABI.md says "
                f"`{want_ret}` — `{want_ret_llvm}` at this width")
        if len(params) != len(want_params):
            failures.append(
                f"{where}: `{name}` takes {len(params)} argument(s), but "
                f"rt/ABI.md says {len(want_params)}")
            continue
        for i, (got, want) in enumerate(zip(params, want_params)):
            want_llvm = _llvm_for(want, int_width)
            if got == want_llvm or (want == "word" and got == "ptr"):
                continue
            failures.append(
                f"{where}: `{name}` argument {i} is `{got}`, but rt/ABI.md "
                f"says `{want}` — `{want_llvm}` at this width")
    if seen == 0:
        failures.append(f"{where}: no documented seam reached the IR at all")


def check_seam_widths(failures):
    for name in SEAM_CORPUS_HOSTED:
        source = os.path.join(ROOT, "examples", name)
        if not os.path.exists(source):
            failures.append(f"{name}: missing from examples/")
            continue
        _check_widths(_emit_ir(source, [], "seams_" + name[:-4]), 64,
                      f"64-bit host ({name})", failures)

    # The 32-bit leg is the one that can tell `word` and `Int64` apart. A
    # freestanding program declares the seams without importing hosted std.
    free_src = os.path.join(ROOT, "examples", SEAM_SOURCE_RV32)
    if not os.path.exists(free_src):
        failures.append(f"examples/{SEAM_SOURCE_RV32} is missing — the "
                        f"32-bit leg has nothing to compile")
        return
    _check_widths(_emit_ir(free_src, RV32, "seams_rv32"), 32, "riscv32",
                  failures)

    # The DEFINE side, over a real runtime seam body: an `@export` of a seam
    # unifies with the compiler's declaration, so this is what a wrong
    # declaration actually corrupts.
    clock = os.path.join(ROOT, "sawc", "rt", "host_macos", "clock.saw")
    if not os.path.exists(clock):
        failures.append("sawc/rt/host_macos/clock.saw is missing — the define "
                        "side has no real seam body to check")
        return
    text = _emit_ir(clock, ["-c", "--runtime-build"] + RV32[1:],
                    "seamdef_rv32")
    _check_widths(text, 32, "riscv32 runtime-build", failures)
    if "__saw_rt_clock_monotonic_nanos" not in _seam_types(text):
        failures.append("riscv32 runtime-build: the clock seam body did not "
                        "reach the IR")


def main() -> int:
    failures = []
    check_embedding(failures)
    check_seam_widths(failures)

    if failures:
        print("IR contract violations:\n")
        for f in failures:
            print(f"  - {f}\n")
        return 1

    print(f"IR contract: {len(EMBED_CORPUS)} programs embed identically with "
          f"and without -c; every documented seam matches rt/ABI.md at 64 and "
          f"32 bits")
    return 0


if __name__ == "__main__":
    sys.exit(main())
